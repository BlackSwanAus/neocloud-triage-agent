---
name: terraform-hyperstack
description: Generate or review Hyperstack HCL Terraform configurations using provider v1.50.2-alpha. Load when designing infrastructure, planning resource changes, or troubleshooting provider issues. Cross-reference against flavor capabilities and MCP tool equivalents to optimize cost and avoid conflicts.
---

# Terraform Hyperstack Provider (v1.50.2-alpha)

Provider: `NexGenCloud/terraform-provider-hyperstack` **v1.50.2-alpha**  
Resources: 8 | Data sources: 24 | References: flavor, region, image, capabilities, MCP mapping

## When to Load This Skill

- Generating HCL for Hyperstack infrastructure (VMs, clusters, volumes, keypairs)
- Reviewing existing Terraform that targets Hyperstack
- Planning single-resource changes (firewall rules, volume attachments)
- Validating flavor selections against capabilities and constraints
- Optimizing cost via MCP direct calls instead of plan/apply

**Do NOT load this skill for:**
- Pure infrastructure reading (use `data "hyperstack_*"` instead)
- Authentication/policy design (auth resources rarely used in TF)
- Architecture discussions (load `hyperstack-triage` for operational context)

## Core Rules (in priority order)

### 1. Flavor & Capability Validation (MANDATORY)

Before emitting any resource with a `flavor_name`:

```
1. Check references/flavor-matrix.tsv for the flavor (49 flavors across 3 regions)
2. Read references/flavor-capabilities.tsv for capability flags (hibernation, snapshots, hard_reboot, network_optimised, bootable-from-volume)
3. If user requests a feature negated by a label (e.g., hibernation on A100-80G-PCIe-Spot), REFUSE with citation:
   "A100-80G-PCIe-Spot has no-hibernation label (from flavor-capabilities.tsv, line X); 
    cannot use hibernation_vm. Recommend A100-80G-PCIe or A100-80G-SXM4 instead."
4. For api-only flavors, note that they are only discoverable/provisionable via API, not UI
```

### 2. Image Validation (MANDATORY)

- **Never hardcode image IDs.** Use computed output from `data "hyperstack_core_images"`:
  ```hcl
  data "hyperstack_core_images" {}
  
  resource "hyperstack_core_virtual_machine" "example" {
    image_name = data.hyperstack_core_images.images[0].name
  }
  ```
- If image_name is user-provided, cross-check against `references/image-matrix.tsv` (auto-populated at deploy time).
- Image-name driver heterogeneity: some images may only be available in certain regions; **always use `core_environment` DS to validate**.

### 3. Region Assignment (MANDATORY)

- **Never hardcode region IDs.** Use:
  ```hcl
  data "hyperstack_core_environment" "target" {
    name = var.environment_name  # CANADA-1, NORWAY-1, US-1
  }
  
  resource "hyperstack_core_virtual_machine" "example" {
    environment_name = data.hyperstack_core_environment.target.name
  }
  ```
- Allowed regions (from `references/region-matrix.tsv`): `CANADA-1` (primary), `NORWAY-1` (EU, RTX A4000 / CPU-only), `US-1` (A100-SXM4 limited).
- **Refuse hardcoded region strings in code.** Always use `data "hyperstack_core_environment"`.

### 4. Stock Pre-check (STRONGLY RECOMMENDED)

When plan requires ≥2 of any single GPU SKU (e.g., H100x8, A100x4):

```hcl
data "hyperstack_core_stocks" "check" {
  region = data.hyperstack_core_environment.target.name
}

# In plan output, verify stock > 0 for all required flavors before apply
```

Run `./scripts/stocks-precheck.sh terraform.tfplan` before high-cost apply.

### 5. Volume Lifecycle Protection (MANDATORY)

Add `lifecycle { prevent_destroy = true }` to:
- `resource "hyperstack_core_volume"`
- `resource "hyperstack_core_keypair"`
- `resource "hyperstack_core_cluster"`

```hcl
resource "hyperstack_core_volume" "data" {
  name              = "app-data"
  environment_name  = "CANADA-1"
  size_gb           = 500
  volume_type       = "SSD"
  
  lifecycle {
    prevent_destroy = true
  }
}
```

### 6. VM Security Group Rules (MANDATORY)

- **Every `core_virtual_machine` must have ≥1 `core_virtual_machine_sg_rule`.**
- **Refuse any rule with CIDR `0.0.0.0/0` (open to internet) unless user provides `# allow-open-internet` comment override.**
  ```hcl
  resource "hyperstack_core_virtual_machine_sg_rule" "ssh_restricted" {
    vm_id       = hyperstack_core_virtual_machine.example.id
    direction   = "ingress"
    protocol    = "tcp"
    port_range_min = 22
    port_range_max = 22
    cidr        = "203.0.113.0/24"  # ✓ Restricted
  }
  
  resource "hyperstack_core_virtual_machine_sg_rule" "http_open" {
    vm_id            = hyperstack_core_virtual_machine.example.id
    direction        = "ingress"
    protocol         = "tcp"
    port_range_min   = 80
    port_range_max   = 80
    cidr             = "0.0.0.0/0"
    # ✓ Comment override present: allow-open-internet
  }
  ```

### 7. Plan vs. Direct MCP Optimization (RECOMMENDED)

**For single-resource mutations, recommend direct MCP calls instead of plan/apply:**

- **Adding a firewall rule:** Use MCP `add_firewall_rule` instead of `terraform apply`
  ```
  "Instead of terraform apply, call: hyperstack mcp call add_firewall_rule 
   --vm-id 12345 --protocol tcp --port-min 443 --port-max 443 --cidr 203.0.113.0/24"
  ```
- **Attaching a volume:** Use MCP `attach_volume_to_vm`
- **Starting/stopping VM:** Use MCP `start_vm` / `stop_vm` (not lifecycle in TF)
- **Multi-resource changes:** Use plan/apply normally

See `references/mcp-tool-mapping.md` for full equivalence table.

### 8. Additive-Only Changes (MANDATORY)

**Never emit `terraform destroy` or any code that deletes resources.** Only generate:
- `resource "hyperstack_*"` (new)
- `data "hyperstack_*"` (lookup)
- Updates to existing resource attributes (computed outputs excluded)

If user requests deletion, respond:
```
"Deletion requests are manual; use: terraform destroy -target resource.name
 or call hyperstack mcp delete_vm / delete_volume directly."
```

### 9. Provider Version Pin (MANDATORY)

Every generated Terraform file must include:

```hcl
terraform {
  required_providers {
    hyperstack = {
      source  = "NexGenCloud/terraform-provider-hyperstack"
      version = "~> 1.50.2-alpha"
    }
  }
}
```

### 10. Flavor Label Awareness (MANDATORY)

Cross-reference user requests against `flavor-capabilities.tsv`:

| Label | Meaning | Refuse Request If |
|-------|---------|-------------------|
| `network_optimised` | SR-IOV high-speed networking | User doesn't need; choose non-opt variant for cost |
| `no-hibernation` | Cannot suspend to disk | User requests `resource.hyperstack_core_virtual_machine` with hibernation ops |
| `no-snapshot` | No point-in-time backup | User requests volume snapshots for flavor with label |
| `local-storage-only` | Cannot boot from Ceph | User sets `create_bootable_volume = true` on restricted flavor |
| `api-only` | Not in UI; API-only discoverable | Note limitation; user must use API/TF to provision |
| `no-reboot` | Cannot hard-reboot | User requests `hard_reboot_vm` MCP call |

## Resource Quick Reference

**8 Resources:**
- `auth_role` (auth, RBAC policy definition)
- `core_cluster` (K8s cluster provisioning)
- `core_environment` (region registration; read-only in practice)
- `core_keypair` (SSH key import)
- `core_virtual_machine` (VM provisioning; **requires ≥1 sg_rule**)
- `core_virtual_machine_sg_rule` (firewall rule; **refuse 0.0.0.0/0 unless commented**)
- `core_volume` (block storage; **protect with prevent_destroy**)
- `core_volume_attachment` (mount volume to VM)

**24 Data Sources:**
- `core_flavors` → `list_flavors` MCP
- `core_images` → computed image list (use for image_name lookup)
- `core_environment` → `get_environment` MCP
- `core_environments` → `list_environments` MCP
- `core_stocks` → `check_stocks` MCP (pre-flight gate)
- `core_regions` → alias for environments
- `core_virtual_machines` → `list_vms` MCP
- `core_clusters` → `list_clusters` MCP
- Auth DSes: use for org context only

## Provenance Block (MANDATORY OUTPUT)

Every generated Terraform code or finding must include provenance:

```json
{
  "provenance": {
    "model_version": "claude-haiku-4-5",
    "prompt_hash": "<SHA256 of system prompt + skills>",
    "provider_version": "1.50.2-alpha",
    "data_sources_called": ["core_flavors", "core_images", "core_stocks"],
    "mcp_tools_called": [],
    "created_at": "2026-05-18T14:05:30Z"
  }
}
```

See `ai-finding-format` skill for schema.

## Workflow Example

**Request:** "Create a 2-GPU H100 VM in CANADA-1 with 500GB volume, SSH key, and restrict access to office network."

**Checks:**
1. ✓ H100x2 flavor found in flavor-matrix.tsv, CANADA-1 region
2. ✓ Check flavor-capabilities.tsv: H100-80GB-PCIe supports all operations
3. ✓ Lookup `core_environment` data for CANADA-1
4. ✓ Check `core_stocks` pre-flight
5. ✓ Generate VM resource with sg_rule (ingress TCP 22 from office CIDR)
6. ✓ Create volume with `prevent_destroy` lifecycle
7. ✓ Emit provenance block

**Generated HCL:**
```hcl
terraform {
  required_providers {
    hyperstack = {
      source  = "NexGenCloud/terraform-provider-hyperstack"
      version = "~> 1.50.2-alpha"
    }
  }
}

data "hyperstack_core_environment" "canada" {
  name = "CANADA-1"
}

data "hyperstack_core_stocks" "check" {
  region = data.hyperstack_core_environment.canada.name
}

data "hyperstack_core_images" "ubuntu" {}

resource "hyperstack_core_keypair" "admin" {
  name       = "admin-key"
  public_key = var.admin_ssh_public_key

  lifecycle {
    prevent_destroy = true
  }
}

resource "hyperstack_core_volume" "data" {
  name             = "app-data"
  environment_name = data.hyperstack_core_environment.canada.name
  size_gb          = 500
  volume_type      = "SSD"

  lifecycle {
    prevent_destroy = true
  }
}

resource "hyperstack_core_virtual_machine" "compute" {
  name                = "h100-compute"
  flavor_name         = "n3-H100x2"
  environment_name    = data.hyperstack_core_environment.canada.name
  image_name          = data.hyperstack_core_images.ubuntu.images[0].name
  assign_floating_ip  = true
  create_bootable_volume = false

  depends_on = [hyperstack_core_keypair.admin, data.hyperstack_core_stocks.check]
}

resource "hyperstack_core_volume_attachment" "data_mount" {
  vm_id     = hyperstack_core_virtual_machine.compute.id
  volume_id = hyperstack_core_volume.data.id
}

resource "hyperstack_core_virtual_machine_sg_rule" "ssh" {
  vm_id          = hyperstack_core_virtual_machine.compute.id
  direction      = "ingress"
  protocol       = "tcp"
  port_range_min = 22
  port_range_max = 22
  cidr           = "203.0.113.0/24"  # Office network
}
```

## References

- `references/resources.tsv` — 8 resources × attributes
- `references/data-sources.tsv` — 24 data sources × attributes
- `references/flavor-matrix.tsv` — 49 flavors with specs (CPU, RAM, GPU, storage)
- `references/flavor-capabilities.tsv` — capability flags per GPU family
- `references/flavor-labels.tsv` — label semantics (network_optimised, no-hibernation, etc)
- `references/region-matrix.tsv` — CANADA-1, NORWAY-1, US-1
- `references/image-matrix.tsv` — OS images (auto-populated at deploy)
- `references/mcp-tool-mapping.md` — resource/DS ↔ MCP tool equivalence (optimization guide)

## Scripts

- `scripts/regen-from-schema.sh` — Regenerate references/resources.tsv and references/data-sources.tsv from provider schema (GitHub CI on every *-alpha tag)
- `scripts/stocks-precheck.sh` — Gate plan with `check_stocks` MCP for GPU SKU availability

## Cross-Skill Integration

- **`evidence-citation`:** Cite artifact path + line when citing constraint violations (e.g., "flavor-capabilities.tsv line 8: no-hibernation label")
- **`ai-finding-format`:** Use provenance block schema for structured output
- **`xid-catalog`:** Not applicable (provider level, not hardware)
- **`hyperstack-triage`:** Load together when diagnosing infrastructure failures post-deploy
