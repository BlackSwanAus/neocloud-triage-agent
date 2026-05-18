# Secret Suppression Patterns

Before emitting verbatim text in an evidence block, scan for and redact the following patterns.

## Credentials and Tokens

| Pattern | Regex | Replace With |
|---------|-------|-------------|
| API Key | `api[_-]?key\s*[:=]\s*[a-zA-Z0-9_\-]{20,}` | `api_key=[REDACTED]` |
| Bearer Token | `Bearer\s+[a-zA-Z0-9_\-]{20,}` | `Bearer [REDACTED]` |
| GitHub Token | `ghp_[a-zA-Z0-9]{36,}` | `ghp_[REDACTED]` |
| AWS Access Key | `AKIA[0-9A-Z]{16}` | `AKIA[REDACTED]` |
| SSH Private Key | `-----BEGIN (RSA\|EC\|DSA\|PGP) PRIVATE` | `-----BEGIN [PRIVATE KEY REDACTED]` |
| Password field | `password\s*[:=]\s*[^\s]{6,}` | `password=[REDACTED]` |

## Personal Information (PII)

| Pattern | Regex | Replace With |
|---------|-------|-------------|
| Email address | `[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}` | `[email@example.com]` |
| Phone number | `\+?[1-9]\d{1,14}` (E.164) | `[phone]` |
| Social Security Number | `\d{3}-\d{2}-\d{4}` | `[SSN]` |
| Credit card | `\d{4}[\s\-]?\d{4}[\s\-]?\d{4}[\s\-]?\d{4}` | `[card XXXX]` |
| IPv4 (internal only) | `192\.168\.\d{1,3}\.\d{1,3}` | `[internal-ip]` |
| IPv6 | `(::)?([0-9a-f]{0,4}:){2,7}[0-9a-f]{0,4}` | `[ipv6]` |

## Cloud and Container IDs

| Pattern | Regex | Replace With |
|---------|-------|-------------|
| AWS Account ID | `\d{12}` (in AWS ARN context) | `[AWS_ACCOUNT]` |
| Kubernetes Pod token | `/run/secrets/kubernetes.io/serviceaccount/token` | `/run/secrets/kubernetes.io/serviceaccount/[REDACTED]` |
| Docker image digest | `sha256:[a-f0-9]{64}` | `sha256:[REDACTED]` |
| Kubernetes secret | `apiVersion: v1\nkind: Secret.*data:.*` (multi-line) | `apiVersion: v1\nkind: Secret\ndata: [REDACTED]` |

## Sensitive Paths and Names

| Pattern | Regex | Replace With |
|---------|-------|-------------|
| Kubernetes namespace with secret names | `namespace=[a-z\-]+` (if PII-like) | `namespace=[REDACTED]` |
| User home directory | `/home/[a-zA-Z0-9_\-]+` | `/home/[user]` |
| Mount path with customer name | `/mnt/customer[_\-][a-zA-Z0-9\-]+` | `/mnt/customer/[REDACTED]` |

## Rules of application

1. **Scan before emit.** Before setting `evidence.verbatim`, run all patterns against the text.
2. **Preserve line integrity.** Redaction should not break the semantic meaning of the line. Prefer `[REDACTED]` over deletion.
3. **Case-insensitive matching.** Use `(?i)` flag for all patterns unless noted.
4. **Log the redaction.** If you redact something, add a note to evidence: `"redacted_fields": ["api_key", "email"]`.
5. **Minimal redaction.** Only redact fields matching the patterns. Do not over-redact (e.g., redacting "password=weak" as a policy; only redact actual secret values).

## Example

**Original line:**
```
2026-05-18T14:05:30 INFO: API call to https://api.example.com with token Bearer ghp_abc123def456ghi789jkl, user=alice@example.com
```

**After redaction:**
```
2026-05-18T14:05:30 INFO: API call to https://api.example.com with token Bearer [REDACTED], user=[email@example.com]
```

**Evidence block:**
```json
{
  "artifact": "...",
  "line": 142,
  "verbatim": "2026-05-18T14:05:30 INFO: API call to https://api.example.com with token Bearer [REDACTED], user=[email@example.com]",
  "redacted_fields": ["github_token", "email"]
}
```
