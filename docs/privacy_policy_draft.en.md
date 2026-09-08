# Privacy Policy / Data Handling Notice (Draft)

> **Updated 2026-09-06**: the cloud remote service (Epic 11.5's API-key
> edition + Epic 11.9's OAuth 2.1 edition) has been genuinely deployed
> and is serving real traffic (`api.yliuai.com`); this document no longer
> labels cloud-related clauses as "planned" -- everything below is
> strictly aligned with the **currently deployed implementation**, and
> doesn't describe anything the code doesn't actually do yet. Known gaps
> are honestly listed in section 8 ("Known gaps"), not glossed over. This
> draft was written by the engineering team, **does not constitute legal
> advice**, and must be reviewed by a qualified lawyer before formal
> publication or submission to Anthropic's Connector Directory review.

## 1. What we collect

- **Local mode** (the stdio MCP server, the `memory-core-mcp` command):
  the text you import/enter, the entities and relations extracted from
  it, along with provenance information (which passage, when) -- stored
  in a SQLite file on your own machine, never automatically uploaded to
  any server.
- **Cloud remote mode** (`api.yliuai.com`, both access methods share the
  same data):
  - **Registration email**: collected via `POST /users/register` for the
    API-key edition, or via the magic-link login form for the OAuth
    edition. Both methods resolve to the same `user_id` namespace, so the
    same email never produces two accounts.
  - **Credentials are stored only as hashes**: the API key, OAuth
    access/refresh tokens, and the magic-link one-time token are all
    stored in the database only as hashes -- the plaintext value is
    returned to you exactly once, at the moment it's generated, and we
    ourselves can't retrieve it afterward (reusing the existing hashing
    pattern in `cloud_api/auth.py`).
  - **Your memory-graph data**: the entities, relations, timestamps, and
    provenance extracted from your text, stored in cloud Postgres,
    strictly isolated by `user_id` (each user's queries can only see
    their own data -- see the cross-tenant isolation tests in
    `tests/test_postgres_store.py`).
  - **Basic call logs**: a timestamp + which tool was called
    (`add_memory`/`search_memory`/etc.), without recording the specific
    content of the call, used for usage accounting (`UsageTracker`).
  - **Audit records for deletions**: every `forget_memory` call records
    one audit-log entry (time, how many entities/relations were deleted),
    but the deleted data itself is not retained in this log (see section
    4).
  - **OAuth client registration info**: for MCP clients (e.g. Claude
    Desktop) that go through Dynamic Client Registration, the
    `client_id`/`redirect_uris`/etc. submitted at registration time --
    this is "which app is connecting" information, not your personal
    data.

## 2. What we don't collect

- Besides your email, we don't require any other personally identifying
  information to use this product (local or cloud).
- We don't log the specific text content you pass into a tool call (the
  "call log" in section 1 is timestamp + tool name only, as noted above).

## 3. Which third parties data passes through

Extracting memories requires calling a large language model, and
retrieval requires calling an embedding model -- data flows differently
for these two steps, disclosed honestly:

- **Large language model (used for triple extraction)**:
  - Local mode: whichever LLM provider you configure yourself via
    environment variables (OpenAI, DeepSeek, etc.) -- your text is sent
    to the provider you chose.
  - Cloud remote mode: this deployment is currently configured to use
    **DeepSeek's API** -- the text you input when calling `add_memory` is
    sent to DeepSeek for processing. Our service itself doesn't
    separately retain that request content, but it does pass through
    DeepSeek's API (as a processor/sub-processor), subject to DeepSeek's
    own privacy policy.
- **Embedding model (used for semantic retrieval)**: cloud remote mode
  runs a locally deployed `sentence-transformers` model, running on our
  own servers -- **your text is never sent to any third party** for this
  step; there's no third-party data egress here.
- **Email delivery (OAuth login only)**: login magic links are sent via
  [Resend](https://resend.com) -- your email address and login link pass
  through Resend's email-delivery infrastructure (as a processor/sub-
  processor), subject to Resend's own privacy policy.
- Besides these two (DeepSeek, Resend), we do not sell or share your data
  with any other third party.

## 4. Your rights: export and deletion

- **Full export at any time**: both local and cloud modes let you call
  `export_memory` at any time to export your complete memory graph
  (entities, relations, timestamps, provenance); see
  [`export_format.md`](export_format.md) for the format. This is a free
  capability, not a paid feature.
- **Complete deletion at any time**: calling `forget_memory` performs a
  physical delete, not a soft-delete flag -- the deletion is recorded in
  a separate audit log (time, how many items deleted), but the deleted
  data itself is not retained in that log. For safety, each call deletes
  at most one best-matching relation, to avoid a vague query deleting too
  much data by mistake (see the "forget_memory real-world verification"
  section in `docs/mcp_quickstart.md`).
- If you want to fully close your account (delete your email/credential
  records themselves, not just your memory data), this currently requires
  contacting us for manual handling (see section 7 for contact info) --
  there isn't yet a self-service account-closure entry point; see section
  8, "Known gaps."

## 5. Data retention period

- We haven't set up an automatic expiration/auto-deletion mechanism for
  memory data -- your data is retained indefinitely until you call
  `forget_memory` yourself, or contact us to close your account. This is
  an honest description of the current state, not a promised product
  design; if an automatic retention-period policy is added later, this
  section will be updated.
- OAuth access tokens (1 hour) / refresh tokens (30 days) are the
  expiration times for authentication credentials, not the retention
  period for your memory data itself -- a credential expiring only means
  you need to log in again, it doesn't delete any memory data.

## 6. Data encryption and transport security -- an honest account of the current state

- **API keys / OAuth credentials**: only hashes are stored in the
  database, so a database leak wouldn't leak usable plaintext
  credentials.
- **Transport encryption**: the client-to-Cloudflare-edge leg is standard
  HTTPS. **Known gap**: the Cloudflare-to-origin-server leg is currently
  in Flexible mode, i.e. plaintext HTTP (not our application-layer
  choice -- determined by the current Cloudflare SSL/TLS mode
  configuration); there's a plan to upgrade to Full mode (installing a
  Cloudflare Origin CA certificate on the origin) so this leg is
  encrypted too -- see the known-limitations record in `TASKS.md`/the
  local ops documentation.
- **Encryption of the memory data itself**: the local SQLite edition
  (`LocalGraphStore`) supports optional Fernet field-level encryption;
  **the cloud Postgres edition currently has no equivalent field-level
  encryption wired in** (data is stored in plaintext in Postgres, relying
  on the server's own access controls -- i.e. listening only on
  `127.0.0.1`, with the database password stored separately). This is a
  real, existing, not-yet-closed gap, not a "planned" feature -- it's the
  actual current state; see section 8.

## 7. Contact

For data questions, export/deletion assistance, or account-closure
requests, email **support@yliuai.com** (forwarded via Cloudflare Email
Routing).

## 8. Known gaps (should be addressed, or at minimum clearly disclosed to users, before formal publication/review submission)

- [ ] Memory data in cloud Postgres has no field-level encryption (see
      section 6).
- [ ] The Cloudflare-to-origin leg is currently plaintext HTTP (Flexible
      mode, see section 6).
- [ ] There's no self-service account-closure entry point; closing an
      account currently requires manual handling (see section 4).
- [ ] Once the billing system starts handling payment information,
      payment-data-processing terms will need to be added (the cloud
      service currently has no billing/charges).
- [ ] Needs a formal review by a qualified lawyer -- this document was
      written by the engineering team and does not constitute legal
      advice.

## 9. Compliance claims we do not make

We do not claim this product "complies with GDPR" or "is protected under
a specific regulation by force of law" -- the export and deletion
capabilities are a product principle we chose proactively, a design that
gets ahead of regulatory trends, not an off-the-shelf compliance
dividend (EU GDPR Article 20's data-portability right doesn't clearly
cover AI-inferred personal profiles/memories today, which is exactly the
part we think most deserves proactive coverage).
