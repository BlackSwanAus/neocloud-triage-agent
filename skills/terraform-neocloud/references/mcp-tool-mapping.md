# Terraform Resource/DataSource → Neocloud MCP Tool Mapping

Maps each Terraform resource and data source to its direct MCP equivalent for optimization recommendations.

## Resources (8 total)

| Resource | Terraform Use Case | MCP Equivalent Read | MCP Equivalent Write | Notes |
|----------|-------------------|-------------------|----------------------|-------|
| `auth_role` | Create/manage IAM roles | `auth_organization`, `auth_permissions` | (no direct write; via API endpoint) | Auth management requires dashboard; no direct MCP write |
| `core_cluster` | Provision Kubernetes clusters | `list_clusters`, `get_cluster`, `list_cluster_versions` | `create_cluster` (write), `delete_cluster` (write) | Large cost impact; `check_stocks` precheck recommended |
| `core_environment` | Register regions (rarely used) | `list_environments`, `get_environment` | (no write; static per region) | Environments are pre-registered; read-only in practice |
| `core_keypair` | Import SSH public keys | (implicit in `get_vm`) | (no direct MCP write; API endpoint only) | Keypairs created via provider; no MCP direct equivalent |
| `core_virtual_machine` | Launch instances | `list_vms`, `get_vm`, `get_vm_events` | `create_vm` (write), `delete_vm` (write), `hard_reboot_vm`, `start_vm`, `stop_vm`, `hibernate_vm`, `restore_vm` | For single resource changes prefer direct MCP calls; `check_stocks` and `list_flavors` precheck |
| `core_virtual_machine_sg_rule` | Security group rules | (implicit in `get_vm`) | `add_firewall_rule` (write), `remove_firewall_rule` (write) | **RECOMMEND MCP DIRECT:** Single rule changes should use `add_firewall_rule` / `remove_firewall_rule` instead of plan |
| `core_volume` | Block storage volumes | `list_volumes`, `get_volume`, `list_volume_types` | `create_volume` (write), `update_volume` (write), `delete_volume` (write) | For single volume ops consider `create_volume` / `delete_volume` direct calls |
| `core_volume_attachment` | Mount volumes to VMs | (implicit in `get_vm`, `get_volume`) | `attach_volume_to_vm` (write), `detach_volume_from_vm` (write), `update_volume_attachment` (write) | **RECOMMEND MCP DIRECT:** Attachment changes should prefer `attach_volume_to_vm` / `detach_volume_from_vm` |

## Data Sources (24 total)

| Data Source | MCP Equivalent Read | Use Case |
|-------------|-------------------|----------|
| `auth_me` | (implicit) | Current user context; no MCP equivalent |
| `auth_organization` | (implicit) | Org context; no MCP equivalent |
| `auth_permissions` | (implicit) | Permission discovery; no MCP equivalent |
| `auth_policies` | (implicit) | Policy enumeration; no MCP equivalent |
| `auth_role` | (implicit) | Single role lookup; no direct MCP read |
| `auth_roles` | (implicit) | Role enumeration; no MCP equivalent |
| `auth_user_me_permissions` | (implicit) | Current user permissions; no MCP equivalent |
| `auth_user_permissions` | (implicit) | User permissions; no MCP equivalent |
| `core_clusters` | `list_clusters` | Enumerate K8s clusters |
| `core_clusters_versions` | `list_cluster_versions` | Available K8s versions |
| `core_dashboard` | (implicit) | System status; no MCP equivalent |
| `core_environment` | `get_environment` | Region detail by name |
| `core_environments` | `list_environments` | Enumerate regions |
| `core_firewall_protocols` | (implicit) | Static protocol list; no MCP equivalent |
| `core_flavors` | `list_flavors` | Enumerate flavors with capabilities |
| `core_gpus` | (implicit) | GPU type enumeration; no MCP equivalent |
| `core_images` | (implicit) | OS images; recommend `data "hyperstack_core_images"` computed |
| `core_keypair` | (implicit) | Keypair lookup; no direct MCP read |
| `core_keypairs` | (implicit) | Enumerate keypairs; no MCP equivalent |
| `core_regions` | `list_environments` | Region enumeration (alias for environments) |
| `core_stocks` | `check_stocks` | **CRITICAL:** Flavor availability pre-flight gate |
| `core_virtual_machines` | `list_vms` | Enumerate VMs |
| `core_volume_types` | `list_volume_types` | Storage classes |
| `core_volumes` | `list_volumes` | Enumerate volumes |

## Cross-Reference Rules

1. **Pre-plan stock check:** Before `terraform plan` that references ≥2 of any GPU SKU, invoke `check_stocks` via MCP.
2. **Single resource changes:** For adding/removing a single firewall rule or volume attachment, use direct MCP calls (not plan).
3. **Flavor validation:** All `flavor_name` references must be checked against `list_flavors` + `flavor-capabilities.tsv` to catch label violations.
4. **Image discovery:** `core_images` DS populates `image-matrix.tsv` at deployment; use computed output, never hardcode image IDs.

## MCP Tool Inventory (38 total)

See `hyperstack-mcp-tools.tsv` for full list of 38 Neocloud MCP tools (20 read / 18 write).
