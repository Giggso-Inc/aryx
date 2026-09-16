# aryx — OCI Deployment Plan

**Version:** 1.0  
**Region:** OCI US Midwest (Chicago) — `us-chicago-1` *(only region with full GenAI support)*  
**Tier:** Always Free by default — paid upgrade callouts marked ⬆️  
**Rule:** Every `<placeholder>` must be replaced before running aryx.

---

## Creation Order (follow this sequence — dependencies matter)

```
1. Tenancy & Auth       ← prereq for everything
2. Compartment          ← logical grouping
3. VCN + Networking     ← prereq for ADB, Compute, Functions
4. Oracle ADB 23ai      ← prereq for Select AI, migrations
5. OCI Object Storage   ← prereq for Document Understanding
6. OCI Generative AI    ← prereq for ADB Select AI credential
7. ADB Post-Config      ← requires ADB + GenAI both ready
8. OCI Doc Understanding← no instance; just IAM + env vars
9. OCI Compute VM       ← runs aryx; requires VCN
10. OCI Functions        ← optional async worker
11. OCI Data Flow        ← optional Spark batch worker
```

---

## Service 1 — OCI Tenancy & Auth *(shared by all services)*

**Console path:** Profile menu (top right) → Tenancy → copy OCID  
**No Free Tier limit** — tenancy auth is always free.

### What to create

| Step | Action |
|------|--------|
| 1 | Create a dedicated IAM user: **Identity → Users → Create User** → name: `aryx-svc-user` |
| 2 | Create a group: **Identity → Groups → Create** → name: `aryx-group` → add `aryx-svc-user` |
| 3 | Generate API key: **Identity → Users → aryx-svc-user → API Keys → Add API Key** → Download private key |
| 4 | Note the fingerprint shown after upload |

### Secrets & config

| Secret / Config | Where to find it | Format | Where used |
|-----------------|-----------------|--------|-----------|
| User OCID | Identity → Users → aryx-svc-user → OCID | `ocid1.user.oc1..xxxxxxxx` | `~/.oci/config` |
| Tenancy OCID | Profile menu → Tenancy → OCID | `ocid1.tenancy.oc1..xxxxxxxx` | `~/.oci/config` |
| Region | Top-right region selector | `us-chicago-1` | `~/.oci/config` |
| API key fingerprint | Shown after uploading public key | `xx:xx:xx:...:xx` (16 hex pairs) | `~/.oci/config` |
| Private key file | Downloaded as `.pem` during API key creation | PEM file path | `~/.oci/config` |

### `~/.oci/config` (local dev only)

```ini
[DEFAULT]
user=ocid1.user.oc1..aaaa<placeholder>
fingerprint=<placeholder>           # e.g. a1:b2:c3:d4:e5:f6:a1:b2:c3:d4:e5:f6:a1:b2:c3:d4
tenancy=ocid1.tenancy.oc1..aaaa<placeholder>
region=us-chicago-1
key_file=~/.oci/aryx_api_key.pem    # path to downloaded private key
```

> **Inside OCI (Compute VM / Functions / Data Flow):** Use Instance Principal instead — no key file needed. aryx auto-detects this via `oci_client.py` singleton.

---

## Service 2 — Compartment

**Console path:** Identity & Security → Compartments → Create Compartment  
**No Free Tier limit** — compartments are always free.

### What to create

| Field | Value |
|-------|-------|
| Name | `aryx-compartment` |
| Description | `aryx knowledge graph pipeline` |
| Parent compartment | Root (or your existing parent) |

### Secrets & config

| Config | Where to find it | Format | aryx env var |
|--------|-----------------|--------|--------------|
| Compartment OCID | Identity → Compartments → aryx-compartment → OCID | `ocid1.compartment.oc1..xxxxxxxx` | `OCI_COMPARTMENT_ID` |

```env
OCI_COMPARTMENT_ID=ocid1.compartment.oc1..aaaa<placeholder>
# Console → Identity → Compartments → aryx-compartment → OCID (copy button)
```

---

## Service 3 — VCN + Networking

**Console path:** Networking → Virtual Cloud Networks → Create VCN  
**Free Tier:** VCN, subnets, security lists, route tables — always free.

### What to create

**VCN:**

| Field | Value |
|-------|-------|
| Name | `aryx-vcn` |
| CIDR block | `10.0.0.0/16` |
| Compartment | `aryx-compartment` |

**Subnets (create 2):**

| Name | CIDR | Type | Used for |
|------|------|------|---------|
| `aryx-public-subnet` | `10.0.0.0/24` | Public | App VM (has public IP) |
| `aryx-private-subnet` | `10.0.1.0/24` | Private | ADB, PGX (no public IP) |

**Security List — ingress rules (add to aryx-public-subnet):**

| Port | Protocol | Source | Purpose |
|------|----------|--------|---------|
| 22 | TCP | 0.0.0.0/0 | SSH to app VM |
| 8088 | TCP | 0.0.0.0/0 | aryx REST API |
| 8501 | TCP | 0.0.0.0/0 | aryx Streamlit UI |
| 3001 | TCP | 0.0.0.0/0 | aryx Next.js web UI |
| 7007 | TCP | 10.0.0.0/16 | Oracle PGX (internal only) |

**Internet Gateway:** Create one, attach to `aryx-vcn`, add to public subnet route table.

### Secrets & config

No aryx env vars needed for the VCN itself. The VCN ID is used when creating Functions and Compute — copy it from **Networking → Virtual Cloud Networks → aryx-vcn → OCID**.

---

## Service 4 — Oracle ADB 23ai

**Console path:** Oracle Database → Autonomous Database → Create Autonomous Database  
**aryx backend toggle:** `ARYX_DB_BACKEND=oci`  
**Free Tier:** 2 instances × (1 OCPU + 20 GB storage) — Always Free, never expires.

### What to create

| Field | Value |
|-------|-------|
| Display name | `aryx-db` |
| Database name | `ARYXDB` |
| Workload type | Transaction Processing |
| Deployment type | Serverless |
| Database version | 23ai |
| ECPU count | 1 (Always Free) ⬆️ 2–4 ECPUs for Small/Large |
| Storage | 20 GB (Always Free) ⬆️ 100–500 GB for paid |
| Auto scaling | Disabled (Always Free) |
| Admin password | Set a strong password — save it |
| Network access | Allow secure access from everywhere (dev) |
| License type | License Included |
| Always Free | ✓ Toggle ON |

After creation:
1. **Download wallet:** ADB → aryx-db → DB Connection → Download Wallet → save as `aryx_wallet.zip`
2. Unzip to `/opt/oracle/wallet/aryx/` (or any path) and set `TNS_ADMIN`
3. Create app user (do NOT use ADMIN for aryx):
```sql
CREATE USER aryx_app IDENTIFIED BY "<placeholder-app-password>";
GRANT DWROLE TO aryx_app;
GRANT UNLIMITED TABLESPACE TO aryx_app;
```
4. Run aryx migrations: `ARYX_DB_BACKEND=oci python -m aryx.store.migrate`

### Secrets & config

| Secret / Config | Where to find it | Format | aryx env var |
|-----------------|-----------------|--------|--------------|
| DSN / service name | Unzip wallet → open `tnsnames.ora` → pick `aryxdb_high` | string | `ARYX_OCI_ADB_DSN` |
| TNS_ADMIN path | Directory where you unzipped the wallet | file path | `TNS_ADMIN` |
| App DB username | Set by you when creating the aryx_app user | string | `ARYX_DB_USER` |
| App DB password | Set by you when creating the aryx_app user | string | `ARYX_DB_PASSWORD` |
| Wallet password | Set when downloading wallet | string | `ARYX_DB_WALLET_PASSWORD` |

```env
ARYX_DB_BACKEND=oci
ARYX_OCI_ADB_DSN=aryxdb_high         # from tnsnames.ora — pick _high, _medium, or _low
TNS_ADMIN=/opt/oracle/wallet/aryx     # directory containing tnsnames.ora + cwallet.sso
ARYX_DB_USER=aryx_app                 # the user you created (NOT admin)
ARYX_DB_PASSWORD=<placeholder>        # password you set for aryx_app
ARYX_DB_WALLET_PASSWORD=<placeholder> # password entered when downloading wallet
```

### ADB Post-Config SQL (run as ADMIN)

```sql
-- 1. Create OCI credential for GenAI / Select AI
BEGIN
  DBMS_CLOUD.CREATE_CREDENTIAL(
    credential_name => 'OCI_GENAI_CRED',
    user_ocid       => 'ocid1.user.oc1..<placeholder>',
    tenancy_ocid    => 'ocid1.tenancy.oc1..<placeholder>',
    private_key     => '<contents of aryx_api_key.pem — paste between BEGIN/END lines>',
    fingerprint     => '<placeholder>'         -- e.g. a1:b2:c3:...
  );
END;
/

-- 2. Create Select AI profile
BEGIN
  DBMS_CLOUD_AI.CREATE_PROFILE(
    profile_name => 'ARYX_SELECTAI',
    attributes   => '{
      "provider": "oci",
      "credential_name": "OCI_GENAI_CRED",
      "object_list": [
        {"owner": "ARYX_APP", "name": "ARYX_ENTITY"},
        {"owner": "ARYX_APP", "name": "ARYX_RELATIONSHIP"},
        {"owner": "ARYX_APP", "name": "ARYX_ONTOLOGY_TYPE"}
      ]
    }'
  );
END;
/

-- 3. Set as default profile
EXEC DBMS_CLOUD_AI.SET_PROFILE('ARYX_SELECTAI');
```

---

## Service 5 — OCI Object Storage

**Console path:** Storage → Object Storage & Archive Storage → Buckets → Create Bucket  
**Free Tier:** 20 GB / month — Always Free.

### What to create (2 buckets)

**Bucket 1 — Document Understanding output:**

| Field | Value |
|-------|-------|
| Name | `aryx-doc-output` |
| Storage tier | Standard |
| Compartment | `aryx-compartment` |
| Versioning | Disabled |
| Lifecycle policy | Create rule: delete objects > 7 days old |

**Bucket 2 — RDF/OWL exports:**

| Field | Value |
|-------|-------|
| Name | `aryx-rdf-exports` |
| Storage tier | Standard |
| Compartment | `aryx-compartment` |
| Versioning | Enabled (retain last 5 versions) |

### IAM policy required

```
Allow group aryx-group to manage object-family in compartment aryx-compartment
```

**Console path:** Identity → Policies → Create Policy → paste statement above.

### Secrets & config

| Config | Where to find it | Format | aryx env var |
|--------|-----------------|--------|--------------|
| Namespace | Storage → Object Storage → Namespace (top of page) | short string e.g. `axkemthipsFT` | `OCI_OBJECT_STORAGE_NAMESPACE` |
| Doc output bucket | Name you chose above | string | `OCI_DOCUMENT_BUCKET` |
| RDF bucket | Name you chose above | string | `OCI_RDF_BUCKET` |

```env
OCI_OBJECT_STORAGE_NAMESPACE=<placeholder>   # Storage → Object Storage → Namespace
OCI_DOCUMENT_BUCKET=aryx-doc-output
OCI_RDF_BUCKET=aryx-rdf-exports
```

---

## Service 6 — OCI Generative AI

**Console path:** Analytics & AI → Generative AI → Overview → Get Started  
**No instance to create** — fully managed API service.  
**Free Tier:** No permanent free tier. OCI Free Trial = $300 USD credits (covers ~3 months at free-tier scale).  
**aryx backend toggles:** `ARYX_EMBED_BACKEND=oci` · `ARYX_LLM_CHEAP_BACKEND=oci` · `ARYX_LLM_FRONTIER_BACKEND=oci`

### What to enable

| Step | Action |
|------|--------|
| 1 | Confirm region is `us-chicago-1` — GenAI not available in all regions |
| 2 | Analytics & AI → Generative AI → confirm service shows "Active" |
| 3 | Auth uses the same API key from Service 1 — no separate credential |

### IAM policy required

```
Allow group aryx-group to use generative-ai-family in compartment aryx-compartment
```

### Secrets & config

| Config | Where to find it | Format | aryx env var |
|--------|-----------------|--------|--------------|
| GenAI endpoint | Fixed per region — us-chicago-1 shown below | URL | `OCI_GENAI_ENDPOINT` |
| Compartment OCID | Same as Service 2 | `ocid1.compartment...` | `OCI_GENAI_COMPARTMENT_ID` |
| Embed model ID | Analytics & AI → GenAI → Models → filter Embed | string | `OCI_GENAI_EMBED_MODEL` |
| Cheap LLM model ID | Analytics & AI → GenAI → Models → filter Chat | string | `OCI_GENAI_MENIAL_MODEL` |
| Frontier LLM model ID | Analytics & AI → GenAI → Models → filter Chat | string | `OCI_GENAI_FRONTIER_MODEL` |

```env
# ── Embedding ─────────────────────────────────────────────────────────────────
ARYX_EMBED_BACKEND=oci
OCI_GENAI_EMBED_MODEL=cohere.embed-multilingual-v3   # verified model ID as of 2026

# ── Entity extraction (cheap tier) ────────────────────────────────────────────
ARYX_LLM_CHEAP_BACKEND=oci
OCI_GENAI_MENIAL_MODEL=cohere.command-r-08-2024      # Command R — $0.000465/call

# ── Ask / brief synthesis (frontier tier) ─────────────────────────────────────
ARYX_LLM_FRONTIER_BACKEND=oci
OCI_GENAI_FRONTIER_MODEL=cohere.command-r-plus-08-2024  # Command R+ — $0.023/query

# ── Shared GenAI connection ────────────────────────────────────────────────────
OCI_GENAI_ENDPOINT=https://inference.generativeai.us-chicago-1.oci.oraclecloud.com
OCI_GENAI_COMPARTMENT_ID=ocid1.compartment.oc1..aaaa<placeholder>
# Auth uses ~/.oci/config (local) or Instance Principal (inside OCI) — no extra key needed
```

> **Model IDs change with new releases.** Verify current IDs at:
> Analytics & AI → Generative AI → Models — filter by type (Chat / Embed).

---

## Service 7 — OCI Document Understanding

**Console path:** Analytics & AI → Document Understanding → Overview  
**No instance to create** — fully managed API service.  
**aryx backend toggle:** `ARYX_PARSE_BACKEND=oci`  
**Free Tier:** First 1,000 pages / month across all features.

### What to enable

| Step | Action |
|------|--------|
| 1 | Confirm service is available in `us-chicago-1` |
| 2 | Create output bucket `aryx-doc-output` (done in Service 5) |
| 3 | Add IAM policy (below) |

### IAM policy required

```
Allow group aryx-group to use ai-service-document-family in compartment aryx-compartment
Allow group aryx-group to manage object-family in compartment aryx-compartment
```

### Secrets & config

| Config | Where to find it | Format | aryx env var |
|--------|-----------------|--------|--------------|
| Namespace | Same as Service 5 | string | `OCI_DOCUMENT_NAMESPACE` |
| Output bucket | `aryx-doc-output` | string | `OCI_DOCUMENT_BUCKET` |
| Compartment OCID | Same as Service 2 | `ocid1.compartment...` | `OCI_DOCUMENT_COMPARTMENT_ID` |

```env
ARYX_PARSE_BACKEND=oci
OCI_DOCUMENT_NAMESPACE=<placeholder>          # Storage → Object Storage → Namespace
OCI_DOCUMENT_BUCKET=aryx-doc-output
OCI_DOCUMENT_COMPARTMENT_ID=ocid1.compartment.oc1..aaaa<placeholder>
OCI_DOCUMENT_FEATURES=TEXT_DETECTION,TABLE_DETECTION,KEY_VALUE_DETECTION
```

---

## Service 8 — OCI Compute VM (App Server)

**Console path:** Compute → Instances → Create Instance  
**Free Tier:** VM.Standard.A1.Flex — 4 OCPU + 24 GB RAM total across all A1 instances (Always Free, ARM-based).

### What to create

| Field | Value |
|-------|-------|
| Name | `aryx-app-server` |
| Placement | `us-chicago-1`, any AD |
| Image | Oracle Linux 8 (recommended) or Ubuntu 22.04 |
| Shape | `VM.Standard.A1.Flex` |
| OCPUs | 4 (Always Free maximum) |
| Memory | 24 GB (Always Free maximum) |
| VCN | `aryx-vcn` |
| Subnet | `aryx-public-subnet` |
| Public IP | Assign automatically |
| SSH key | Paste your public key (generate with `ssh-keygen -t ed25519`) |
| Boot volume | 100 GB (50 GB Always Free — 50 GB additional at ~$1.28/month) |

⬆️ **Paid upgrade:** Switch to `VM.Standard.E4.Flex` 2–4 OCPU for higher single-thread x86 performance (~$36–73/month).

### Post-provision setup

```bash
# SSH in
ssh -i ~/.ssh/id_ed25519 opc@<public-ip>

# Install Docker
sudo dnf install -y docker
sudo systemctl enable --now docker
sudo usermod -aG docker opc

# Install Docker Compose
sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-linux-aarch64" \
  -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose

# Clone aryx and configure
git clone https://github.com/Giggso-Inc/aryx.git
cd aryx
cp .env.example .env   # then fill in all <placeholder> values
```

### Secrets & config

| Config | Where to find it | Format | Where used |
|--------|-----------------|--------|-----------|
| VM public IP | Compute → Instances → aryx-app-server → Public IP | IPv4 | SSH, API endpoint |
| SSH private key | Generated locally by you | PEM / OpenSSH | `ssh -i key opc@<ip>` |

No aryx env vars point to the VM itself — the `.env` file runs on the VM.

---

## Service 9 — OCI Functions *(optional — async ingest worker)*

**Console path:** Developer Services → Functions → Applications → Create Application  
**aryx backend toggle:** `ARYX_WORKER_BACKEND=oci_functions`  
**Free Tier:** 2,000,000 calls/month + 400,000 GB-sec/month — Always Free.

### What to create

**Application:**

| Field | Value |
|-------|-------|
| Name | `aryx-pipeline` |
| VCN | `aryx-vcn` |
| Subnets | `aryx-private-subnet` |
| Shape | GENERIC_X86 or GENERIC_ARM |

**Function (inside the application):**

| Field | Value |
|-------|-------|
| Name | `aryx-ingest-fn` |
| Runtime | Python 3.11 |
| Memory | 512 MB |
| Timeout | 300 seconds |
| Image | Push from OCIR: `<region>.ocir.io/<namespace>/aryx/aryx-ingest-fn:latest` |

### IAM policy required

```
Allow dynamic-group aryx-functions-dg to use secret-family in compartment aryx-compartment
Allow dynamic-group aryx-functions-dg to use autonomous-database-family in compartment aryx-compartment
Allow dynamic-group aryx-functions-dg to use generative-ai-family in compartment aryx-compartment
```

Create dynamic group first: **Identity → Dynamic Groups → Create** → matching rule:
```
resource.type = 'fnfunc', resource.compartment.id = 'ocid1.compartment.oc1..<placeholder>'
```

### Secrets & config

| Config | Where to find it | Format | aryx env var |
|--------|-----------------|--------|--------------|
| Function OCID | Functions → aryx-pipeline → aryx-ingest-fn → OCID | `ocid1.fnfunc...` | `ARYX_OCI_INGEST_FN_ID` |

```env
ARYX_WORKER_BACKEND=oci_functions
ARYX_OCI_INGEST_FN_ID=ocid1.fnfunc.oc1.us-chicago-1.<placeholder>
# Console → Developer Services → Functions → aryx-pipeline → aryx-ingest-fn → OCID
```

---

## Service 10 — OCI Data Flow *(optional — Spark batch worker)*

**Console path:** Analytics & AI → Data Flow → Applications → Create Application  
**aryx backend toggle:** `ARYX_WORKER_BACKEND=oci_dataflow`  
**Free Tier:** No free tier — billed at $0.02/OCPU-hour (typically $0.07–0.09 per batch job).

### What to create

| Field | Value |
|-------|-------|
| Name | `aryx-pipeline-spark` |
| Language | Python |
| Spark version | 3.3 |
| Driver shape | `VM.Standard.E4.Flex` — 2 OCPU, 32 GB |
| Executor shape | `VM.Standard.E4.Flex` — 2 OCPU, 32 GB |
| Num executors | 4 (auto-scale 1–10) |
| Script location | `oci://aryx-doc-output@<namespace>/spark/aryx_pipeline.py` |
| Logs location | `oci://aryx-doc-output@<namespace>/logs/` |

### IAM policy required

```
Allow group aryx-group to manage dataflow-family in compartment aryx-compartment
Allow group aryx-group to manage object-family in compartment aryx-compartment
```

### Secrets & config

| Config | Where to find it | Format | aryx env var |
|--------|-----------------|--------|--------------|
| Application OCID | Data Flow → Applications → aryx-pipeline-spark → OCID | `ocid1.dataflowapplication...` | `ARYX_OCI_DATAFLOW_APP_ID` |

```env
ARYX_WORKER_BACKEND=oci_dataflow
ARYX_OCI_DATAFLOW_APP_ID=ocid1.dataflowapplication.oc1.us-chicago-1.<placeholder>
# Console → Analytics & AI → Data Flow → Applications → aryx-pipeline-spark → OCID
```

---

## Master `.env` Template

Copy this to `.env` on your app VM and fill in every `<placeholder>`:

```env
# ══════════════════════════════════════════════════════════════════════════════
# aryx — OCI deployment .env
# All <placeholder> values must be replaced before starting aryx
# ══════════════════════════════════════════════════════════════════════════════

# ── OCI Core ──────────────────────────────────────────────────────────────────
OCI_COMPARTMENT_ID=ocid1.compartment.oc1..aaaa<placeholder>
# Console → Identity → Compartments → aryx-compartment → OCID

OCI_REGION=us-chicago-1

# ── OCI Auth (local dev only — not needed inside OCI with Instance Principal) ─
# OCI_CONFIG_FILE=~/.oci/config
# OCI_CONFIG_PROFILE=DEFAULT

# ── Database — Oracle ADB 23ai ────────────────────────────────────────────────
ARYX_DB_BACKEND=oci

ARYX_OCI_ADB_DSN=aryxdb_high
# Open wallet zip → tnsnames.ora → pick service name ending in _high / _medium / _low

TNS_ADMIN=/opt/oracle/wallet/aryx
# Path to directory where you unzipped Wallet_ARYXDB.zip

ARYX_DB_USER=aryx_app
# The non-ADMIN user you created in ADB

ARYX_DB_PASSWORD=<placeholder>
# Password you set for aryx_app user in ADB

ARYX_DB_WALLET_PASSWORD=<placeholder>
# Password entered when downloading the wallet from OCI Console

# ── Object Storage ────────────────────────────────────────────────────────────
OCI_OBJECT_STORAGE_NAMESPACE=<placeholder>
# Console → Storage → Object Storage → top of page shows namespace

OCI_DOCUMENT_BUCKET=aryx-doc-output
OCI_RDF_BUCKET=aryx-rdf-exports

# ── Generative AI — Embedding ─────────────────────────────────────────────────
ARYX_EMBED_BACKEND=oci

OCI_GENAI_ENDPOINT=https://inference.generativeai.us-chicago-1.oci.oraclecloud.com
OCI_GENAI_COMPARTMENT_ID=ocid1.compartment.oc1..aaaa<placeholder>
# Same as OCI_COMPARTMENT_ID unless GenAI is in a different compartment

OCI_GENAI_EMBED_MODEL=cohere.embed-multilingual-v3
# Console → Analytics & AI → Generative AI → Models → filter type=Embed → copy Model ID

# ── Generative AI — Extraction (cheap / menial tier) ──────────────────────────
ARYX_LLM_CHEAP_BACKEND=oci

OCI_GENAI_MENIAL_MODEL=cohere.command-r-08-2024
# Console → Analytics & AI → Generative AI → Models → filter type=Chat → copy Model ID

# ── Generative AI — Ask & Brief synthesis (frontier tier) ─────────────────────
ARYX_LLM_FRONTIER_BACKEND=oci

OCI_GENAI_FRONTIER_MODEL=cohere.command-r-plus-08-2024
# Console → Analytics & AI → Generative AI → Models → filter type=Chat → copy Model ID

# ── Document Understanding ────────────────────────────────────────────────────
ARYX_PARSE_BACKEND=oci

OCI_DOCUMENT_NAMESPACE=<placeholder>
# Same as OCI_OBJECT_STORAGE_NAMESPACE

OCI_DOCUMENT_COMPARTMENT_ID=ocid1.compartment.oc1..aaaa<placeholder>
# Same as OCI_COMPARTMENT_ID

OCI_DOCUMENT_FEATURES=TEXT_DETECTION,TABLE_DETECTION,KEY_VALUE_DETECTION

# ── Worker — OCI Functions (optional — choose one worker backend) ──────────────
# ARYX_WORKER_BACKEND=oci_functions
# ARYX_OCI_INGEST_FN_ID=ocid1.fnfunc.oc1.us-chicago-1.<placeholder>
# Console → Developer Services → Functions → aryx-pipeline → aryx-ingest-fn → OCID

# ── Worker — OCI Data Flow (optional — large-scale Spark batch) ───────────────
# ARYX_WORKER_BACKEND=oci_dataflow
# ARYX_OCI_DATAFLOW_APP_ID=ocid1.dataflowapplication.oc1.us-chicago-1.<placeholder>
# Console → Analytics & AI → Data Flow → Applications → aryx-pipeline-spark → OCID

# ── Graph (optional — Oracle Property Graph) ──────────────────────────────────
# ARYX_GRAPH_BACKEND=oci_graph
# (uses ARYX_OCI_ADB_DSN above — no separate connection needed)
```

---

## IAM Policies — Consolidated

Add all required policies in one place: **Identity → Policies → Create Policy** in `aryx-compartment`.

| Service | Policy statement |
|---------|-----------------|
| Object Storage | `Allow group aryx-group to manage object-family in compartment aryx-compartment` |
| Document Understanding | `Allow group aryx-group to use ai-service-document-family in compartment aryx-compartment` |
| Generative AI | `Allow group aryx-group to use generative-ai-family in compartment aryx-compartment` |
| ADB | `Allow group aryx-group to use autonomous-database-family in compartment aryx-compartment` |
| Functions (dynamic group) | `Allow dynamic-group aryx-functions-dg to use autonomous-database-family in compartment aryx-compartment` |
| Functions (dynamic group) | `Allow dynamic-group aryx-functions-dg to use generative-ai-family in compartment aryx-compartment` |
| Data Flow | `Allow group aryx-group to manage dataflow-family in compartment aryx-compartment` |

---

## Free Tier Summary

| Service | Free Tier | Upgrade trigger |
|---------|-----------|----------------|
| Oracle ADB 23ai | 1 OCPU + 20 GB (Always Free) | Storage > 20 GB or need > 1 OCPU |
| OCI Compute (app VM) | 4 OCPU + 24 GB A1.Flex (Always Free) | Need x86 or > 24 GB RAM |
| OCI Object Storage | 20 GB / month (Always Free) | Total stored docs > 20 GB |
| OCI Functions | 2M calls + 400K GB-sec / month (Always Free) | > ~2,000 docs/month |
| OCI Document Understanding | 1,000 pages / month | > 125 docs/month (at 8 pages avg) |
| OCI Generative AI | **No free tier** — first call is billed | Always pay from doc 1 |
| OCI Networking | Always Free | Never (VCN/subnets are always free) |
| OCI Container Registry | 500 MB / month (Always Free) | Image > 500 MB |

---

## Post-Deployment Verification

```bash
# 1. ADB connection
python3 -c "
import oracledb
conn = oracledb.connect(user='aryx_app', password='<pw>', dsn='aryxdb_high')
print('ADB OK:', conn.version)
conn.close()
"

# 2. Run migrations
ARYX_DB_BACKEND=oci python -m aryx.store.migrate

# 3. API health check
curl http://<vm-public-ip>:8088/health

# 4. Ingest one document
curl -X POST http://<vm-public-ip>:8088/ingest/file \
  -F "file=@test.pdf" -F "workspace_id=1"

# 5. Run one Ask query
curl -X POST http://<vm-public-ip>:8088/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "What entities exist?", "workspace_id": 1}'
```

---

*aryx OCI Deployment Plan — v1.0 — generated 2026-06-23*
