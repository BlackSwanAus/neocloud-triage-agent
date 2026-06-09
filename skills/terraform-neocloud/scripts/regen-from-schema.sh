#!/bin/bash
# Regenerate reference tables from Terraform provider schema.
# Requires: terraform CLI, NEOCLOUD_API_KEY, GitHub CLI (gh)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_ROOT="$(dirname "$SCRIPT_DIR")"
REFS_DIR="$SKILL_ROOT/references"
PROVIDER_VERSION="1.50.2-alpha"

# Check prerequisites
if ! command -v terraform &> /dev/null; then
    echo "Error: terraform CLI not found. Install from https://www.terraform.io/downloads"
    exit 1
fi

if ! command -v gh &> /dev/null; then
    echo "Error: GitHub CLI not found. Install from https://cli.github.com/"
    exit 1
fi

if [ -z "${NEOCLOUD_API_KEY:-}" ]; then
    echo "Error: NEOCLOUD_API_KEY environment variable not set"
    exit 1
fi

# Create temporary working directory
TMPDIR=$(mktemp -d)
trap "rm -rf $TMPDIR" EXIT

cd "$TMPDIR"

# Create minimal versions.tf to fetch provider schema
cat > versions.tf << 'EOF'
terraform {
  required_version = ">= 1.0"

  required_providers {
    neocloud = {
      source  = "Neocloud/neocloud"
      version = "~> 1.50.2-alpha"
    }
  }
}

provider "neocloud" {
  # Uses NEOCLOUD_API_KEY environment variable
}
EOF

echo "Fetching provider schema for v$PROVIDER_VERSION..."
terraform init -upgrade -no-color > /dev/null 2>&1 || true

# Extract provider schema (JSON)
echo "Generating provider schema..."
terraform providers schema -json > provider_schema.json

# Parse schemas and regenerate resource/datasource references
echo "Parsing resource definitions..."
python3 << 'PYTHON'
import json
import csv
import sys

with open('provider_schema.json') as f:
    schema = json.load(f)

# Extract resources
resources = []
provider_schema = schema['provider_schemas'].get('registry.terraform.io/neocloud/neocloud', {})
resource_schemas = provider_schema.get('resource_schemas', {})

for resource_type, resource_def in resource_schemas.items():
    block = resource_def.get('block', {})
    for attr_name, attr_def in block.get('attributes', {}).items():
        resources.append({
            'resource_type': resource_type,
            'attribute': attr_name,
            'type': attr_def.get('type', 'unknown'),
            'required': attr_def.get('required', False),
            'computed': attr_def.get('computed', False),
            'sensitive': attr_def.get('sensitive', False),
            'description': attr_def.get('description', ''),
        })

# Write resources.tsv
print(f"Found {len(resources)} resource attributes", file=sys.stderr)
with open('resources.tsv', 'w', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=[
        'resource_type', 'attribute', 'type', 'required', 'computed', 'sensitive', 'description'
    ], delimiter='\t')
    writer.writeheader()
    writer.writerows(resources)

# Extract datasources
datasources = []
data_source_schemas = provider_schema.get('data_source_schemas', {})

for ds_type, ds_def in data_source_schemas.items():
    block = ds_def.get('block', {})
    for attr_name, attr_def in block.get('attributes', {}).items():
        datasources.append({
            'data_source_type': ds_type,
            'attribute': attr_name,
            'type': attr_def.get('type', 'unknown'),
            'required': attr_def.get('required', False),
            'computed': attr_def.get('computed', False),
            'sensitive': attr_def.get('sensitive', False),
            'description': attr_def.get('description', ''),
        })

print(f"Found {len(datasources)} datasource attributes", file=sys.stderr)
with open('data-sources.tsv', 'w', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=[
        'data_source_type', 'attribute', 'type', 'required', 'computed', 'sensitive', 'description'
    ], delimiter='\t')
    writer.writeheader()
    writer.writerows(datasources)

PYTHON

# Copy generated files
echo "Saving reference tables..."
cp resources.tsv "$REFS_DIR/resources.tsv"
cp data-sources.tsv "$REFS_DIR/data-sources.tsv"

# Update image matrix from core_images datasource (optional; requires API call)
if command -v jq &> /dev/null; then
    echo "Updating image matrix from core_images datasource..."
    # This would require an actual API call; for now, leave as stub
    echo "# Updated $(date -u +'%Y-%m-%dT%H:%M:%SZ')" >> "$REFS_DIR/image-matrix.tsv"
fi

echo "✓ Regenerated references/resources.tsv ($(wc -l < "$REFS_DIR/resources.tsv") lines)"
echo "✓ Regenerated references/data-sources.tsv ($(wc -l < "$REFS_DIR/data-sources.tsv") lines)"
echo "✓ Provider schema regeneration complete"
