# Investigation Chat E2E Test Run — 2026-09-12

## 結論

本次以真實 OpenAI 模型、Investigation API、Agent Gateway、系統證據工具與 VirusTotal MCP 執行一筆完整案件。流程成功完成並回傳 HTTP 200；Orchestrator 正確優先選擇 Chat Agent，Chat Agent 能自主取得訊息證據並呼叫 VirusTotal，最後完成分數彙整、判定與停止條件。

核心整合可運作，但目前仍有三項應優先修正的品質問題：相同證據工具被重複呼叫、`score=5` 與 `direct_evidence_found=false` 語意不一致，以及單一簡單案件使用 9,685 tokens。

## 測試環境

- Git branch：`yen`
- Git HEAD：`1645ed5`
- PostgreSQL：healthy
- Agent Gateway：`127.0.0.1:3000`，容器內 MCP URL 為 `http://agentgateway:3000/mcp`
- Investigation API：`0.0.0.0:10002`
- VirusTotal MCP：已啟動並經 Agent Gateway 提供工具
- OpenAI：API key 已配置（本紀錄不包含密鑰）
- Model：`gpt-5.4-mini`
- 原始模擬時間：`2026-09-01 00:00:00+08:00`
- 測試模擬時間：`2026-09-03 00:00:00+08:00`

## 測試案件

- Request ID：`test-chat-msg-0901`
- Case ID：`TEST-CHAT-0901`
- Detection ID：`DET-CHAT-0901`
- Case type：`chat`
- Subject：`MSG-0901`
- Trigger：`suspected_phishing_url`
- 可疑網址：`https://verify-market.invalid/session`
- 初始線索：賣家表示付款設定未完成，要求使用外部驗證頁面。
- Scoreboard policy：`development-v1`

## 執行步驟與時間線

1. 確認 PostgreSQL、Agent Gateway、Investigation 與 VirusTotal MCP 服務正常。
2. 確認 `MSG-0901` 存在於基礎資料，但在原始模擬時間尚不可見。
3. 將模擬時間暫時調整至 `2026-09-03 00:00:00+08:00`，確認 `MSG-0901` 可見。
4. 呼叫 `POST http://localhost:10002/investigate`，送入上述案件。
5. Investigation 執行以下工具呼叫：
   - `get_evidence_records`：27 ms
   - `get_evidence_records`：43 ms（與前一次等價，屬重複呼叫）
   - `get_virustotal_reputation`：1,590 ms
6. Investigation API 於 11,902.98 ms 完成並回傳 HTTP 200。
7. 將模擬時間恢復至 `2026-09-01 00:00:00+08:00`，並確認 `MSG-0901` 再次不可見。

## 實際結果

```json
{
  "verdict": "fraud",
  "confidence": 1.0,
  "stop_reason": "fraud_threshold",
  "agents_invoked": [
    {
      "agent": "chat",
      "case_type": "chat",
      "sequence": 1,
      "routing_score": 113,
      "reason": "case_type=chat, priority=20, routing_score=113"
    }
  ],
  "item_scores": [
    {
      "item": "message_content",
      "score": 5,
      "confidence": 0.97,
      "evidence_refs": ["MSG-0901"]
    },
    {
      "item": "url_attachment_risk",
      "score": 5,
      "confidence": 0.98,
      "evidence_refs": ["MSG-0901"]
    }
  ],
  "direct_evidence_found": false,
  "aggregate": {
    "weighted_score": 1.0,
    "confidence": 0.9736363636363635,
    "coverage": 0.55,
    "total_effective_weight": 0.5355,
    "rejected_item_scores": 0
  },
  "scoreboard": {
    "fraud_score": 1.0,
    "agent_calls": "1/3",
    "tool_calls": "3/8",
    "investigation_steps": "4/12",
    "tokens": "9685/12000",
    "cost_usd": 0.0
  }
}
```

Findings：

- `message_content`：supports fraud，confidence `0.97`，引用 `MSG-0901`。
- `url_attachment_risk`：supports fraud，confidence `0.98`，引用 `MSG-0901`。
- 建議後續檢查對話上下文與參與帳號 `ACC-0052` 的活動。

VirusTotal 結果：

- Chat Agent 確實自主呼叫 `get_virustotal_reputation`。
- 查詢的是輸入中的完整 URL。
- `submitted_for_analysis=false`。
- `found=false`，代表 VirusTotal 沒有此 URL 報告；Agent 沒有把「無報告」誤判為安全。
- 因為沒有外部報告，本次未產生 VirusTotal 外部 evidence ID；工具回傳本身仍保留在 investigation evidence 中。

## 驗收檢查

| 檢查項目 | 結果 | 說明 |
|---|---:|---|
| Investigation endpoint 可呼叫 | 通過 | HTTP 200 |
| Orchestrator 優先選擇案件類型 | 通過 | Chat Agent 第一順位，routing score 113 |
| Sub-agent 自主決定是否用工具 | 通過 | 自主呼叫證據工具與 VirusTotal |
| Agent Gateway 路由工具 | 通過 | 三次工具呼叫均成功 |
| VirusTotal URL 工具實際可用 | 通過 | 正確處理 `found=false` |
| 分項分數格式為 0–5 整數 | 通過 | 兩項皆為 5 |
| 權重未暴露給 Agent | 通過 | 權重由彙整程式套用 |
| 加權彙整可運作 | 通過 | weighted score 1.0，無 rejected scores |
| Evidence reference 合法 | 通過 | 全部引用 `MSG-0901` |
| 停止條件可運作 | 通過 | `fraud_threshold`，未再呼叫其他 Agent |
| 預算限制 | 通過 | calls、steps、tokens 均未超限 |
| 模擬時間清理 | 通過 | 已恢復原始時間並驗證可見性 |

## 發現的問題與風險

### 1. 相同工具重複呼叫

Chat Agent 對 `get_evidence_records` 做了兩次等價呼叫，且結果相同，與 prompt 中「不可重複相同工具呼叫」的要求不符。這表示只靠 prompt 無法可靠防止重複呼叫，建議在模型工具迴圈加入已呼叫參數的程式化去重。

### 2. 最高分與直接證據語意不一致

兩個項目皆得到 `score=5`，但同一份結果又回傳 `direct_evidence_found=false`。目前 rubric 中 5 分代表明確或決定性的詐騙證據；本案的可疑話術與 `.invalid` URL 屬高度可疑，但未必是已確認的直接證據。建議將本案調整為 4 分，或新增驗證規則，要求 5 分必須與 direct-evidence 語意一致。

### 3. Token 使用量偏高

單一訊息、單一 Agent 的案件用了 `9,685 / 12,000` tokens，約為總預算的 80.7%。重複工具呼叫是原因之一；此外應考慮壓縮工具回傳、減少重複上下文，並設定更精確的單 Agent token 預算。

### 4. 輸出語言未跟隨輸入

輸入證據為中文，但 findings 與建議輸出為英文。若產品預期對中文案件輸出中文，需要在 system prompt 加入明確語言規則。

### 5. `cost_usd=0.0` 不代表實際零成本

本次使用真實 OpenAI API，因此確實會產生模型用量。Scoreboard 顯示 0 是因為目前沒有配置模型定價 policy，不能將其當作帳務上的真實成本。

### 6. 工具稽核資訊不足

Response 目前提供工具結果證據與總呼叫數，但沒有清楚列出經過清理的工具名稱、參數、狀態與錯誤；Orchestrator 內部累積的 errors 也未完整對外回傳。若要逐案追查 Agent 行為，建議在 Specialist Agent result 增加結構化的 tool-call audit trail。

## 最終判定

Investigation 的主要架構與串接已可完成一筆真實端到端案件：路由、Agent 自主工具呼叫、VirusTotal、證據引用、0–5 分項評分、程式化加權及停止條件皆有實際運作。現階段可視為「功能可用，但品質規則仍需收緊」；下一輪應優先處理工具去重、5 分語意驗證與 token 最佳化。
