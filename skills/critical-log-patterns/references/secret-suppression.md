# Secret suppression — re-apply before emitting `verbatim`

Even though gather-info redacts at collection time, assume bypass. Run these regexes over every `evidence.verbatim` string before emission and replace matches with `[REDACTED]`.

## Patterns (case-insensitive)

```
(?i)^(TOKEN|AWS_SECRET_ACCESS_KEY|AWS_ACCESS_KEY_ID|GITHUB_TOKEN|GH_TOKEN|SLACK_TOKEN|VAULT_TOKEN|NPM_TOKEN|PYPI_TOKEN|CARGO_REGISTRY_TOKEN|OPENAI_API_KEY|ANTHROPIC_API_KEY|HF_TOKEN|HUGGINGFACE_TOKEN|HUGGINGFACE_API_KEY|DATABASE_URL|PGPASSWORD|MYSQL_PWD|REDIS_PASSWORD|.*(?:PASSWORD|PASSWD|PSK|SECRET|CREDENTIAL|API[_-]?KEY|AUTH[_-]?TOKEN|PRIVATE[_-]?KEY))$

(?i)\b(password|passwd|secret|token|credential|api[_-]?key|auth[_-]?token|private[_-]?key|seedfrom)=(\S+)

(?i)--(password|passwd|secret|token|api[_-]?key|credential)(?:=|\s+)([^\s]+)

(?i)(Authorization:\s*)(Bearer|Basic)\s+[^\s]+

(?i)(wpa-psk)\s+\S+

\bgh[opusr]_[A-Za-z0-9]+\b                # GitHub PATs
\bxox[baprs]-[A-Za-z0-9-]+\b              # Slack tokens
\bAKIA[0-9A-Z]{16}\b                      # AWS access key id
-----BEGIN (?:RSA |EC |OPENSSH |DSA |)?PRIVATE KEY-----    # PEM markers
```

## IP-port shaped lines (privacy)

```
from \d+\.\d+\.\d+\.\d+ port \d+
```

Replace IP octets with `x` (preserve port number for triage value): `from x.x.x.x port 22`.

## Hex blob heuristic

```
\b[0-9a-f]{64,}\b
```

Long lowercase hex strings (≥64 chars) are almost always keys/hashes. Replace with `[REDACTED_HEX]` unless the context is clearly a Git SHA (40 chars) or PCIe BDF (already extracted).
