import type { CaseInvestigation, FraudCase } from "@/types/case";

export const cases: FraudCase[] = [
  { id:"CASE-2026-0912-0841", subject:"acct_8f3a19", subjectType:"account", status:"review", verdict:"fraud", fraudScore:.91, confidence:.94, triggers:["Dirty IP","Mass messaging","Scam keyword"], updatedAt:"10:42", summary:"帳號在短時間內大量傳送含外部付款連結的訊息，登入 IP 與已知詐欺群組重疊。", evidenceCount:8, invokedAgents:["Chat Agent","Order Agent"] },
  { id:"CASE-2026-0912-0828", subject:"shop_northstar", subjectType:"shop", status:"review", verdict:"suspicious", fraudScore:.73, confidence:.81, triggers:["Refund anomaly","Shared device"], updatedAt:"10:31", summary:"退款行為偏離同類商店基準，且多個關聯帳號共用相同裝置。", evidenceCount:5, invokedAgents:["Order Agent","Shop Agent"] },
  { id:"CASE-2026-0912-0817", subject:"acct_21bc04", subjectType:"account", status:"review", verdict:"suspicious", fraudScore:.68, confidence:.76, triggers:["Multiple IP login"], updatedAt:"10:18", summary:"帳號在不合理時間內由三個不同國家登入，需要人工確認帳號是否遭接管。", evidenceCount:4, invokedAgents:["Chat Agent"] },
  { id:"CASE-2026-0912-0794", subject:"acct_72de90", subjectType:"account", status:"investigating", verdict:"unknown", triggers:["Scam keyword"], updatedAt:"09:56", summary:"調查仍在進行，目前沒有足夠證據形成系統詐欺分數。", evidenceCount:2, invokedAgents:["Chat Agent"] },
  { id:"CASE-2026-0912-0766", subject:"shop_alto_goods", subjectType:"shop", status:"normal", verdict:"normal", fraudScore:.12, confidence:.89, triggers:["Volume spike"], updatedAt:"09:34", summary:"促銷活動造成的正常流量增加，已由調查證據確認。", evidenceCount:6, invokedAgents:["Order Agent","Shop Agent"] }
];

export const casesApi = {
  async list(): Promise<FraudCase[]> { return structuredClone(cases); },
  async get(id: string): Promise<FraudCase | undefined> { return structuredClone(cases.find((item) => item.id === id)); }
};

const primaryInvestigation: CaseInvestigation = {
  detectionId: "DET-0912-4812",
  investigationId: "INV-0912-2197",
  stopReason: "direct_evidence_threshold_met",
  invocations: [
    { order:1, component:"Detection", status:"submitted", reason:"三項偵測規則觸發，建立案件並提交調查。", inputRefs:["account:acct_8f3a19"], output:"detected=true；觸發 Dirty IP、Mass messaging、Scam keyword。未產生系統 Fraud Score。", evidenceRefs:["EV-0841-01","EV-0841-02"], durationMs:82 },
    { order:2, component:"Investigation Orchestrator", status:"completed", reason:"根據觸發條件規劃證據收集順序。", inputRefs:["DET-0912-4812","scoreboard-config:v3"], output:"依序呼叫 Chat Agent 與 Order Agent，並要求驗證外部網址及交易行為。", evidenceRefs:[], durationMs:41 },
    { order:3, component:"Chat Agent", status:"completed", reason:"確認訊息是否含有詐欺話術與站外付款引導。", inputRefs:["EV-0841-01"], output:"辨識出 7 則站外付款引導訊息，縮網址目的地與既有詐欺活動相符。", evidenceRefs:["EV-0841-03","EV-0841-04"], durationMs:1840, agentRef:{parent:"investigation",slug:"chat",version:"registry-snapshot"} },
    { order:4, component:"Transaction Agent", status:"completed", reason:"核對訂單、付款與退款資料是否支持對話中的說法。", inputRefs:["order:ord_7c120","account:acct_8f3a19"], output:"平台內無對應付款紀錄；相同收款帳號出現在 4 起已確認詐欺案件。", evidenceRefs:["EV-0841-05"], durationMs:923, agentRef:{parent:"investigation",slug:"transaction",version:"registry-snapshot"} },
    { order:5, component:"Investigation Verdict", status:"completed", reason:"彙整獨立證據並套用 Scoring Policy v5。", inputRefs:["EV-0841-03","EV-0841-04","EV-0841-05","EV-0841-06"], output:"verdict=fraud；fraud_score=0.91；confidence=0.94。", evidenceRefs:["EV-0841-03","EV-0841-05","EV-0841-06"], durationMs:116 }
  ],
  evidence: [
    { id:"EV-0841-01", source:"Detection / message_stream", type:"message", observedAt:"2026-09-12 10:37:14", collectedBy:"Detection", summary:"5 分鐘內向 23 名不同買家傳送 41 則訊息。", raw:{account_id:"acct_8f3a19",window_seconds:300,message_count:41,unique_recipients:23,rule:"mass_messaging_v2",threshold:20}},
    { id:"EV-0841-02", source:"Environment DB / auth_log", type:"login_ip", observedAt:"2026-09-12 10:36:02", collectedBy:"Detection", summary:"登入 IP 命中內部高風險情報，與 6 個停權帳號共享。", raw:{ip:"185.220.101.34",country:"DE",asn:60729,risk_tags:["tor_exit","shared_with_banned_accounts"],linked_banned_accounts:6,last_seen:"2026-09-12T02:36:02Z"}},
    { id:"EV-0841-03", source:"Chat transcript / msg_90142", type:"message", observedAt:"2026-09-12 10:38:21", collectedBy:"Chat Agent", summary:"要求買家透過外部連結完成付款，並以限時優惠施壓。", raw:{message_id:"msg_90142",sender:"acct_8f3a19",recipient:"acct_buyer_771",language:"zh-TW",text:"系統刷卡有問題，今天內用這個連結付款可以再折 8%，不要從平台下單。",url_refs:["url_17ab"],classifier:{label:"off_platform_payment_solicitation",probability:0.97}}},
    { id:"EV-0841-04", source:"URL Intelligence / url_17ab", type:"url_reputation", observedAt:"2026-09-12 10:39:06", collectedBy:"Chat Agent", summary:"縮網址重新導向仿冒結帳頁，網域建立僅 3 天。", raw:{submitted_url:"https://s-pay.help/a8K2",final_url:"https://secure-checkout-tw.cc/pay",http_status:200,domain_age_days:3,reputation:"malicious",detections:{phishing:12,clean:1,unknown:9},tls_issuer:"Let's Encrypt"}},
    { id:"EV-0841-05", source:"System DB / transactions", type:"transaction", observedAt:"2026-09-12 10:40:11", collectedBy:"Order Agent", summary:"相關訂單未在平台內付款；外部收款帳號關聯 4 起詐欺案件。", raw:{order_id:"ord_7c120",platform_payment_status:"unpaid",amount_twd:12800,external_payment_account:"bank_hash_92c1",related_confirmed_cases:["CASE-2026-0828-0412","CASE-2026-0903-0631","CASE-2026-0908-0722","CASE-2026-0910-0804"]}},
    { id:"EV-0841-06", source:"Association / device_graph", type:"device", observedAt:"2026-09-12 10:40:37", collectedBy:"Investigation Orchestrator", summary:"裝置指紋關聯 3 個已確認詐欺帳號及同一高風險 IP。", raw:{device_fingerprint:"dev_fp_6ea42",confidence:0.96,linked_accounts:[{id:"acct_91de22",verdict:"fraud"},{id:"acct_02aa71",verdict:"fraud"},{id:"acct_776bc9",verdict:"fraud"}],shared_ip:"185.220.101.34"}}
  ]
};

export function getCaseInvestigation(id: string): CaseInvestigation {
  if (id === "CASE-2026-0912-0841") return primaryInvestigation;
  if (id === "CASE-2026-0912-0794") return { ...primaryInvestigation, detectionId:"DET-0912-4729", investigationId:"INV-0912-2142", stopReason:"investigation_in_progress", evidence:primaryInvestigation.evidence.slice(0,2), invocations:[
    { ...primaryInvestigation.invocations[0], status:"completed" },
    { ...primaryInvestigation.invocations[1], status:"completed" },
    { ...primaryInvestigation.invocations[2], status:"running", output:"正在分析最近 30 天的對話樣本…", evidenceRefs:[], durationMs:624 }
  ] };
  return { ...primaryInvestigation, detectionId:`DET-${id.slice(-4)}`, investigationId:`INV-${id.slice(-4)}`, evidence:primaryInvestigation.evidence.slice(0,2), invocations:primaryInvestigation.invocations.slice(0,4) };
}
