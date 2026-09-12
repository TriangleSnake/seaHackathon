# 本次測試使用的檔案

## 原始測試產物

- `request.json`：實際送往 `POST /investigate` 的 request body
- `response.json`：Investigation endpoint 回傳的原始 response body
- `service.log`：本次 request 對應的 Investigation 與 Agent Gateway 原始日誌

## Investigation 執行程式

- `services/investigation/app/main.py`
- `services/investigation/app/api/routes.py`
- `services/investigation/app/core/orchestrator.py`
- `services/investigation/app/agents/base.py`
- `services/investigation/app/agents/chat.py`
- `services/investigation/app/gateways/openai.py`
- `services/investigation/app/gateways/mcp.py`
- `services/investigation/app/evidence/ledger.py`
- `services/investigation/app/scoring/weighted.py`
- `services/investigation/app/scoring/engine.py`
- `services/investigation/app/domain/models.py`
- `services/investigation/app/prompts/chat.md`
- `services/investigation/config/scoreboard.development.json`

## Agent Gateway 與工具

- `agentgateway/config.yaml`
- `services/system-tools/app/server.py`
- `services/virustotal-tools/app/server.py`
- `services/virustotal-tools/app/client.py`

## Environment 與共享合約

- `environment/schema.sql`
- `environment/seed.sql`
- `shared/schemas/investigation.schema.json`
- `shared/schemas/detection.schema.json`
- `shared/schemas/common.schema.json`
- `shared/schemas/scoreboard.schema.json`

## 啟動設定

- `docker-compose.yml`
- `.env`（僅載入本機環境變數；未收錄或輸出其中的秘密）

