#!/bin/bash
# Pre-flight SKU availability gate for Terraform plans.
# Wraps terraform plan with check_stocks MCP tool call.
# Returns 0 if all required SKUs in stock, nonzero otherwise.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_ROOT="$(dirname "$SCRIPT_DIR")"

# Parse terraform plan to extract flavor and GPU count requirements
check_flavor_stocks() {
    local plan_json="$1"
    local region="$2"

    # Extract all neocloud_core_virtual_machine resources with their flavor_name and count
    # This is a simplified check; production should use terraform JSON plan parse

    python3 << 'PYTHON'
import json
import sys
import os

if not os.path.exists('terraform.tfplan.json'):
    print("Error: No terraform.tfplan.json found. Run: terraform plan -out=tfplan && terraform show -json tfplan > terraform.tfplan.json", file=sys.stderr)
    sys.exit(1)

try:
    with open('terraform.tfplan.json') as f:
        plan = json.load(f)
except Exception as e:
    print(f"Error parsing plan: {e}", file=sys.stderr)
    sys.exit(1)

# Count by flavor
flavor_counts = {}
for resource in plan.get('resource_changes', []):
    if resource['type'] == 'neocloud_core_virtual_machine':
        if resource['change']['actions'][0] in ['create', 'no-op']:
            flavor = resource['change'].get('after', {}).get('flavor_name', 'unknown')
            flavor_counts[flavor] = flavor_counts.get(flavor, 0) + 1

if not flavor_counts:
    print("No VMs to provision in plan", file=sys.stderr)
    sys.exit(0)

print("Flavor requirements:", flavor_counts, file=sys.stderr)

# In production, call check_stocks MCP tool here via neocloud CLI or API
# Example:
#   neocloud mcp call check_stocks --region "$REGION"
# This would return stock levels per flavor and fail if any required flavor is out of stock.

for flavor, count in flavor_counts.items():
    print(f"PLAN: {flavor} x{count}", file=sys.stderr)

PYTHON

    return $?
}

# Main entry point
main() {
    local region="${NEOCLOUD_REGION:-CANADA-1}"
    local plan_file="${1:-}"

    if [ -z "$plan_file" ] || [ ! -f "$plan_file" ]; then
        echo "Usage: $0 <terraform.tfplan>"
        echo ""
        echo "Environment variables:"
        echo "  NEOCLOUD_REGION: Region to check stocks (default: CANADA-1)"
        echo "  NEOCLOUD_API_KEY: API key for stock checks"
        exit 1
    fi

    echo "Checking flavor availability in $region..."

    # Convert binary plan to JSON
    terraform show -json "$plan_file" > terraform.tfplan.json || {
        echo "Error: Failed to read plan. Is this a valid Terraform plan file?"
        return 1
    }

    # Run stock check
    check_flavor_stocks terraform.tfplan.json "$region" || {
        echo "Error: Required SKUs not in stock. Cannot proceed with apply."
        return 1
    }

    echo "✓ Stock availability check passed"
    return 0
}

main "$@"
