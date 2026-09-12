# Fraud Intelligence System

以台灣電商情境為背景的詐騙偵測與調查 Hackathon 專案。Environment 提供可重現的假資料，Detection 找出可疑訊號，Investigation 蒐集證據並產出判定；System 管理跨服務工作，Dashboard 提供操作介面。Evolution、Evaluator 與 Governance 負責候選防禦策略的建立、比較與審核。

本專案是開發／展示系統，不是已驗證的生產風控產品。**Detection 命中代表需要調查，不代表已確認詐騙，也不是系統的 fraud score。**

## 授權與第三方資料

本 repository 的原始程式碼目前尚未宣告專案 license。Cofacts 衍生的
Environment seed 內容採 CC BY-SA 4.0；AgentGateway v1.5.0 採 Apache-2.0。
完整來源、使用範圍及顯名聲明請見 [Third-Party Notices](THIRD_PARTY_NOTICES.md)。

## 架構與責任

| 元件 | 責任 | 程式與文件 |
| --- | --- | --- |
| Environment | PostgreSQL 16 假賣場資料、事件時間線與 simulation-time 可見資料 | [environment](environment/README.md) |
| Detection | 規則、時間窗異常與可選 LLM 分類，輸出訊號及證據 | [detection](services/detection/README.md) |
| Investigation | LLM Orchestrator 協調專家代理，依指定 scoreboard 調查與判定 | [investigation](services/investigation/README.md) |
| Patrol | 主動探索、排程與非同步巡查工作 | [patrol](services/patrol) |
| Association | 從案件／主體探索關聯對象 | [association](services/association) |
| System | 事件游標、排程、工作佇列、跨代理路由與模型設定 | [system](services/system/README.md) |
| Dashboard | Next.js／React 操作介面，分為 Live 與 Demo 模式 | [dashboard](services/dashboard) |
| Evolution | 策略修改提案、候選版本與迭代流程 | [evolution](services/evolution/README.md) |
| Evaluator | 固定資料及時間比較 baseline／candidate，隔離 validation／holdout | [evaluator](services/evaluator/README.md) |
| Governance | 固定安全門檻與人工審核，不自行啟用策略 | [governance](services/governance/README.md) |
| CODE builder | 隔離容器中建立與驗證 Detection 程式碼候選 | [codex-builder](services/codex-builder/README.md) |

主要執行關係如下；路由是否執行仍取決於工作 payload、策略與條件：

```text
Environment 可見事件 → System → Detection → Investigation → Association
                         ↑          ↑                          │
                       Patrol       └──── 關聯主體再次偵測 ────┘

Evolution → 候選 artifact → Evaluator → Governance → 版本管理
                          baseline/candidate
```

Agent 的資料工具透過 `agentgateway` 存取 `system-tools`；外部網址信譽查詢走獨立的 `virustotal-tools`。Detection 本身直接讀取 Environment，不必透過 MCP gateway。

## 快速開始

需要 Git，以及已啟動的 Docker Engine／Docker Desktop 與 Docker Compose v2。以下命令均從 repository 根目錄執行。

```bash
git clone https://github.com/TriangleSnake/seaHackathon.git
cd seaHackathon
# 已有專案時，先確認沒有未保存修改，再執行 git pull --ff-only。
test -f .env || cp .env.example .env
```

`.env` 請留在本機，不要提交 API key。現有 `.env` 不會自動取得新增設定，更新後請對照 [.env.example](.env.example)。

### 只看 Dashboard 展示

不需要 LLM key，也不需要初始化資料庫：

```bash
docker compose up -d --build dashboard-demo
```

開啟 **http://localhost:3002**。Demo 使用固定 mock／seed 展示資料；看到畫面不代表真實後端已連通。

### 只開 Environment 與 Detection

```bash
docker compose up -d --build postgres detection
docker compose ps
curl --fail-with-body http://localhost:10001/ready
```

預設 `rule_based` 與 `anomaly` 不需要 LLM key。`/health` 確認服務存活；`/ready` 檢查資料庫依賴，不代表 LLM 可用或所有 schema migration 都已完成。

### 完整堆疊與 Live Dashboard

在 `.env` 設定 `OPENAI_API_KEY` 後，使用下列命令建置堆疊。這裡透過 Compose override 將 System 加入服務共用網路，不修改原本的 Compose 檔案：

```bash
docker compose -f docker-compose.yml -f - up -d --build <<'YAML'
services:
  system:
    networks:
      - fraud-intelligence-network
YAML
docker compose ps
docker compose logs --tail=100 detection system dashboard
```

Live Dashboard 位於 **http://localhost:3001**，使用實際 backend；沒有接上的 API 顯示 unavailable，不以 Demo 資料替代。

後續重建完整堆疊時，也使用上述帶有網路 override 的命令。

### 環境變數

| 設定 | 用途 | 預設／使用方式 |
| --- | --- | --- |
| `POSTGRES_DB` | 資料庫名稱 | `fraud_intelligence` |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` | 資料庫帳密 | 依 `.env.example`；部署時自行設定 |
| `OPENAI_API_KEY` | LLM 服務認證 | 純規則 Detection 與 Demo 不需要 |
| `OPENAI_MODEL` | 共用代理模型設定 | 依 `.env.example` |
| `DETECTION_OPENAI_MODEL` | Detection 分類模型 | `gpt-4.1-mini` |
| `DEFAULT_DETECTION_POLICY_VERSION` | Detection 預設策略版本 | `baseline-v1` |
| `VIRUSTOTAL_API_KEY` | 網址／網域信譽查詢 | 使用該工具時設定 |
| `DASHBOARD_PORT` / `DASHBOARD_DEMO_PORT` | Dashboard 對外 port | `3001` / `3002` |

System 的模型控制 API 可設定各元件的模型與 reasoning effort；設定會保存到新建工作，透過 request-scoped headers 傳給代理。直接呼叫服務時，環境變數作為啟動預設值。

### 預設連線位置

| 服務 | 本機網址／port | Compose 內部位置 |
| --- | --- | --- |
| Dashboard Live | http://localhost:3001 | `dashboard:3000` |
| Dashboard Demo | http://localhost:3002 | `dashboard-demo:3000` |
| Detection | http://localhost:10001/docs | `detection:8000` |
| Investigation | http://localhost:10002/docs | `investigation:8000` |
| Patrol | http://localhost:10003/docs | `patrol:10003` |
| Association | http://localhost:10004/docs | `association:10004` |
| System | http://localhost:10005/docs | `system:10005` |
| Governance | http://localhost:10008/docs | `governance:8000` |
| MCP gateway | http://localhost:3000/mcp | `agentgateway:3000/mcp` |
| PostgreSQL | `localhost:5432` | `postgres:5432` |

Port 可透過 [docker-compose.yml](docker-compose.yml) 對應環境變數覆寫。資料庫容器名稱是 `environment-db`，Compose service 名稱仍為 `postgres`；預設 database 為 `fraud_intelligence`。

預設帳密僅供本機開發。除 MCP gateway 明確綁定 `127.0.0.1` 外，其他 port mapping 不應視為僅限本機存取；不要直接暴露到公網。

## Environment：假資料與時間

資料包含帳號、賣場、商品、對話、登入、安全設定、付款、交易、配送、退款、爭議與檢舉。先建立正常行為，再加入少量可疑連續事件與容易誤判的正常對照。

目前 seed 包含 120 個帳號、105 個商品、107 筆交易、467 則訊息、273 筆登入、113 筆付款嘗試與 12 筆爭議。這是完整 seed 的數量，不是初始模擬時間下全部可見的數量。

- 初始 simulation time：`2026-09-01 00:00:00+08`。
- 原始表保留完整時間線；`visible_*` views 只提供當時可見資料。
- `visible_products` 使用當時有效價格；原始 `products.price` 不隨模擬時間覆寫。
- Marketplace rows 不含 `is_fraud` 等答案欄位。Evaluator 的人工標註留在獨立 manifest，不傳入 Detection。
- 可疑訊息參考 Cofacts 電商詐騙主題改寫，不直接載入原始聊天個資；來源及授權見 [Environment attribution](environment/README.md#cofacts-attribution)。

`schema.sql`、`seed.sql` **只在 PostgreSQL volume 為空時初始化**。`git pull`、重建 image 或 restart 不會自動更新既有 DB。既有 DB 應先備份，再依差異套用 migration；不要把新版 seed 重跑到已有資料的 DB。

**不要為了更新程式執行 `docker compose down -v`：它會刪除資料庫 volume。** 單純停止服務可用 `docker compose stop`。

## Detection：呼叫與輸出

Detection 是被呼叫的偵測 API，**不是所有 DB INSERT／UPDATE 都會自動觸發的 database trigger**。來源包含直接 `POST /detect`、System 手動工作、已啟用的事件策略，以及 Patrol／Association 發現後交由 System 派送的工作。System 的 seed 事件策略與排程預設停用，可透過控制 API 啟用；路由實作見 [control.py](services/system/app/control.py)。

以下示範需使用可自行調整時間的開發 DB，**不要對共用或 Evaluator 正在使用的 DB 執行**。把模擬時間移至示範訊息已可見的日期：

```bash
docker compose exec -T postgres sh -c \
  'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1' <<'SQL'
SELECT set_simulation_time(TIMESTAMPTZ '2026-09-10 12:00:00+08');
SQL

curl --fail-with-body -i http://localhost:10001/detect \
  -H 'Content-Type: application/json' \
  -d '{
    "subject": {"type": "message", "id": "MSG-0901"},
    "requested_checks": ["rule_based", "anomaly"],
    "policy_ref": {"type": "detection", "version": "baseline-v1"}
  }'
```

主體尚未在當下時間出現時，回覆 `404 subject_not_found`，不應當成安全判定。

### 三種檢查

- `rule_based`：檢舉、可疑站外付款／驗證訊息、安全變更與新裝置登入、共用商品圖片、退款／爭議等結構化規則。
- `anomaly`：依模擬時間的固定時間窗，檢查訊息、上架、登入裝置／國家、付款工具與爭議等異常。這是門檻檢查，不是訓練好的 ML 模型。
- `llm_classifier`：預設不執行，需指定檢查及 `OPENAI_API_KEY`。請求一個 `true`／`false` token，依兩者 log probabilities 正規化後的 `P(true) >= 0.6` 觸發。缺少所需機率資訊視為無法判斷，不猜答案。實際模型參數相容性需另做 live 驗證。

`message` scope 只對目標訊息及直接相關檢舉做規則判斷；LLM 可額外讀取同對話最多 20 則更早訊息。同時間或更晚的訊息不作為背景。帳號層級登入、付款等行為請使用 `account` scope。

結果的重要欄位為 `detected`、`policy_ref`、`triggers`、`evidence`、`component_results`。成功回應的 `X-Detection-Policy-Version` header 表示實際執行版本。

**HTTP 200 或 `detected: false` 不保證全部檢查成功。** 應確認選定元件的 `component_results` 都為 `completed`；`failed`／`unavailable` 不是乾淨的陰性結果。完整 sample result 與錯誤語意見 [Detection README](services/detection/README.md)。

### Policy 與公平比較

Detection policy 是 JSON config，選擇已註冊的 `(detector type, version)` 並覆寫參數；Python 實作是另一個版本層次。

- 用 `policy_ref.version` 指定 baseline 或 candidate；不存在的版本回覆 `404 policy_not_found`，不偷偷改跑 active policy。
- `POST /policies/detection/test` 可測試 inline policy，不會 publish 或變更 active pointer。
- 比較時固定資料、simulation time、subject 與 requested checks，僅切換 policy。
- 每次請求使用自己的 repeatable-read transaction；兩次請求並不天然共享同一個 DB snapshot。
- Evaluator 應使用隔離 Environment。SnapshotGuard 是前後一致性檢查，不是跨服務鎖。

## Evolution、Evaluator 與 Governance

策略改進流程由 Python composition root 組合 planner、ConfigBuilder、Evaluator、Governance 與 VersionManager，見 [integration README](services/integration/README.md)。這個流程與長駐 HTTP 服務分開執行。

- **提案與建置：** planner 根據 PatternSpec 產生修改意圖。CONFIG builder 支援 `rule_based.chat_request_phrases` 的 typed add／remove，產生不可變候選 JSON artifact。
- **公平比較：** Evaluator 對相同主體、資料與時間執行 baseline／candidate，計算 precision、recall、F1、誤報與增量效益。
- **修訂：** validation 聚合結果可驅動下一輪提案；holdout 不提供給 planner 調參。
- **審核：** Governance 先執行固定門檻檢查，再依設定要求人工決策，保留稽核紀錄。
- **版本責任：** VersionManager 管理候選與正式版本的生命週期；Detection policy 發布／回滾由其 policy API 管理。審核與執行中的 active policy 是不同責任。
- **程式碼候選：** CODE builder 在隔離環境修改限定的 Detection 檔案，執行驗收與回歸測試，產出含 base commit、candidate commit 與測試來源的 metadata。程式碼候選和 config policy 有各自的版本識別。

Evaluation 使用獨立 DB 與固定 simulation time。標註及評估門檻由 Evaluator 保管，不放入 Marketplace rows、Detection request 或 builder 的可見資料。

## 測試與驗證

### Detection 單元／API 回歸

```bash
docker build --target test -t fraud-detection-test services/detection
docker run --rm fraud-detection-test
```

未設定 `DETECTION_TEST_DATABASE_URL` 時，DB integration tests 會跳過，不能當成包含真實 DB 的完整驗證。DB 測試需另外提供載入 schema／seed 的**可丟棄隔離資料庫**；部分測試會調整 simulation time。

### Environment 完整性與資料品質

以下從容器內取得帳密，不依賴主機 shell 是否載入 `.env`：

```bash
docker compose exec -T postgres sh -c \
  'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -f /workspace/environment/tests/integrity.sql'
docker compose exec -T postgres sh -c \
  'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -f /workspace/environment/tests/quality.sql'
```

其他測試與先決依賴請看各服務 README。MCP smoke test 見下文；它不代表所有代理或 Evolution loop 都已驗證。

## API contracts（v0.2）

跨服務契約以 [shared/schemas](shared/schemas) 的 JSON Schema Draft 2020-12 為準。HTTP 服務可查看對應 `/docs`。

| HTTP 入口 | 請求 → 回應 | Schema |
| --- | --- | --- |
| `POST /detect` | `DetectionRequest` → `DetectionResult` | [detection](shared/schemas/detection.schema.json) |
| `POST /investigate` | `InvestigationRequest` → `InvestigationResult` | [investigation](shared/schemas/investigation.schema.json) |
| `POST /patrol/run` | `PatrolRequest` → `PatrolResult` | [patrol](shared/schemas/patrol.schema.json) |
| `POST /associate` | `AssociationRequest` → `AssociationResult` | [association](shared/schemas/association.schema.json) |
| `POST /governance/review` | `GovernanceRequest` → `GovernanceResult` | [governance](shared/schemas/governance.schema.json) |

Python runtime 使用的契約包括 [EvolutionRequest／Result](shared/schemas/evolution.schema.json)、[BuildRequest／CandidateResult](shared/schemas/candidate.schema.json) 與 [EvaluationRequest／Result](shared/schemas/evaluation.schema.json)。

System 常用入口：

- `GET /control/triggers`、`PUT /control/triggers/{policy_id}`：事件觸發策略。
- `GET /control/schedules`、`PUT /control/schedules/{schedule_id}`：持久化排程。
- `GET /control/models`、`PUT /control/models/{component}`：代理模型設定。
- `POST /jobs`、`GET /jobs`、`GET /jobs/{job_id}`：提交與追蹤工作。
- `GET /cases`、`GET /cases/{case_id}`：查詢案件。

Detection policy 管理入口：

- `GET /policies/detection`：列出版本。
- `POST /policies/detection/validate`：驗證 config。
- `POST /policies/detection/drafts`：保存草稿。
- `POST /policies/detection/test`：不啟用的試跑。
- `POST /policies/detection/publish`：發布策略。
- `POST /policies/detection/rollback/{version}`：切回指定版本。

追蹤建議使用 HTTP `X-Request-ID` 與 W3C `traceparent`，避免在每份 JSON body 重複放入追蹤資訊。

## MCP 工具與資料存取

`agentgateway` 將 PostgreSQL domain tools 與 VirusTotal 唯讀信譽查詢整合成 MCP 入口。主機 port 綁定 `127.0.0.1`；容器使用 `http://agentgateway:3000/mcp`。

```text
Agent -> http://localhost:3000/mcp -> agentgateway -> system-tools -> PostgreSQL
                                               `-> virustotal-tools -> VirusTotal API
```

啟動 gateway 與其依賴後，執行 MCP smoke test：

```bash
./scripts/smoke-test-mcp.sh
```

唯讀 domain tools 包括：

- `database_health`
- `search_accounts`
- `get_account_activity`
- `find_shared_ip_accounts`
- `find_shared_device_accounts`
- `get_entity_neighbors`
- `get_previous_cases`
- `get_evidence_records`
- `get_virustotal_reputation`（Chat Agent 使用）

不提供任意 SQL 執行工具。新增資料能力應以有明確範圍的 domain tool 實作，維持存取限制與查詢筆數上限。

## 評分與安全邊界

- Detection 只提供訊號、原始 detector 輸出與證據，不計算系統 fraud score。
- [scoreboard.schema.json](shared/schemas/scoreboard.schema.json) 由 System/control plane 擁有，定義評分門檻、代理／工具／步數／token／成本預算與停止條件。
- Investigation 使用指定的不可變 `scoreboard_config_ref`，回傳 `ScoreboardState` 供稽核與重現。
- Token budget `0` 表示不限額；使用真實 LLM 前請確認成本設定。
- 修改 active policy、調整 simulation time 與一般唯讀偵測是不同操作；評估及實驗請使用隔離環境。

## 本機開發與專案目錄

```text
environment/          PostgreSQL schema、seed、migration 與資料品質測試
services/             各代理、控制平面、Dashboard 與策略改進元件
shared/schemas/       跨服務 JSON Schema
agentgateway/         MCP proxy 設定
scripts/              驗證腳本
docs/                 設計與測試紀錄
docker-compose.yml    開發容器設定
.env.example          環境變數範本
```

Dashboard 可在本機以 Node.js／npm 開發：

```bash
cd services/dashboard
npm ci
npm run dev:demo
# 另一個終端可執行 npm run dev:live，並設定可連線的 backend URLs。
```

Python 服務各自維護 dependencies 與測試，請在各服務獨立的 virtual environment 安裝，不共用不同服務的 `app` import 路徑。具體測試命令見各服務 README。

更新既有 checkout：

```bash
git status
git pull --ff-only
# 依修改範圍重建服務，例如：
docker compose up -d --build detection
```

`git pull` 更新程式，不會替正在執行的容器換版本，也不會遷移既有資料庫。

## 常見操作與排查

| 狀況 | 檢查方式 |
| --- | --- |
| 只想展示介面 | 啟動 `dashboard-demo`，開啟 port `3002` |
| Live 顯示 unavailable | 查看 backend URL、服務 logs 與共用 Docker network |
| Detection `/ready` 回覆 503 | 查看 `docker compose logs postgres detection` 與資料庫連線設定 |
| `subject_not_found` | 確認 ID、subject type，以及 simulation time 是否已包含該資料 |
| `policy_not_found` | 列出 Detection policies，確認版本已提供給該執行環境 |
| LLM `check_unavailable`／`check_inconclusive` | 檢查 key、requested checks、模型與回傳的 log probabilities |
| pull 後資料仍相同 | 正常：volume 保留資料，更新 schema 應使用 migration |
| 需要暫停容器 | `docker compose stop`，保留資料庫 volume |

完整的資料初始化、simulation-time 操作及 Cofacts 授權資訊見 [Environment README](environment/README.md)。
