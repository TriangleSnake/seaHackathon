export const patrolRuns = [
  {id:"PTR-0912-031",mode:"scheduled",scope:"高風險賣家與新註冊帳號",started:"10:00",duration:"06:42",discoveries:7,status:"completed"},
  {id:"PTR-0912-030",mode:"manual",scope:"外部付款連結關聯群組",started:"09:22",duration:"12:18",discoveries:14,status:"completed"},
  {id:"PTR-0912-029",mode:"scheduled",scope:"全站增量巡查",started:"08:00",duration:"—",discoveries:3,status:"running"},
  {id:"PTR-0912-028",mode:"scheduled",scope:"高退款率商店",started:"06:00",duration:"08:51",discoveries:2,status:"completed"}
];

export const discoveries = [
  {subject:"acct_54ba20",reason:"向多個買家傳送相同外部付款網址",priority:"critical",evidence:4,detection:"triggered",caseId:"CASE-2026-0912-0859"},
  {subject:"shop_lumen_tw",reason:"退款率與共用裝置群組同時異常",priority:"high",evidence:7,detection:"triggered",caseId:"CASE-2026-0912-0851"},
  {subject:"acct_118caa",reason:"新帳號短時間大量刊登高價商品",priority:"medium",evidence:3,detection:"pending",caseId:"—"},
  {subject:"acct_99d270",reason:"登入 IP 與已停權群組重疊",priority:"high",evidence:5,detection:"triggered",caseId:"CASE-2026-0912-0848"}
];

export const patterns = [
  {id:"PAT-2026-044",name:"假客服物流補款",confidence:.93,cases:18,gap:"現行規則未辨識物流狀態截圖搭配短網址的組合",status:"evaluating",signals:["偽造物流截圖","NT$30–80 補款","6 小時內換域名"],counterexamples:2},
  {id:"PAT-2026-043",name:"分散式低額測卡",confidence:.86,cases:31,gap:"單一帳號交易量低於規則門檻",status:"candidate_ready",signals:["多帳號共用裝置","單筆 < NT$200","失敗後快速換卡"],counterexamples:5},
  {id:"PAT-2026-042",name:"高仿商店接管",confidence:.79,cases:9,gap:"缺少商店視覺相似度特徵",status:"building",signals:["商店名稱同形字","複製商品圖","新收款帳號"],counterexamples:3}
];

export const defenseVersions = [
  {version:"v13",status:"candidate",base:"v12",created:"2026-09-12 09:48",candidate:"CAND-044",evaluation:"EVAL-0912-18",policies:5,precision:.94,recall:.89,cost:.42},
  {version:"v12",status:"active",base:"v11",created:"2026-09-08 16:20",candidate:"CAND-041",evaluation:"EVAL-0908-11",policies:5,precision:.92,recall:.84,cost:.38},
  {version:"v11",status:"retired",base:"v10",created:"2026-08-29 11:05",candidate:"CAND-038",evaluation:"EVAL-0829-07",policies:4,precision:.90,recall:.81,cost:.36},
  {version:"v10",status:"retired",base:"v9",created:"2026-08-14 08:32",candidate:"CAND-032",evaluation:"EVAL-0814-03",policies:4,precision:.88,recall:.78,cost:.34}
];

export const policies = [
  {category:"Detection Policy",version:"v8",status:"active",created:"2026-09-08",source:"Evolution / PAT-041",defense:"v12",description:"規則觸發、異常偵測與 LLM classifier 路由。"},
  {category:"Scoring Policy",version:"v5",status:"active",created:"2026-09-08",source:"Risk Platform",defense:"v12",description:"Evidence impact 加權與 verdict 判定門檻。"},
  {category:"Investigation Policy",version:"v7",status:"active",created:"2026-09-08",source:"Fraud Ops",defense:"v12",description:"Agent 選擇、停止條件與調查深度。"},
  {category:"Patrol Policy",version:"0.1.0",status:"active",created:"2026-08-29",source:"services/patrol/policies",defense:"runtime",description:"Exploit／Explore 的工具權限、證據要求與探索預算。"},
  {category:"Association Policy",version:"0.1.0",status:"active",created:"2026-09-08",source:"services/association/policies",defense:"runtime",description:"Focused／Discovery 的工具權限、關聯指引與圖搜尋限制。"}
];

export const systemServices = [
  ["System","system:8080","healthy","18 ms","v0.2.1"],["Detection","detection:8081","healthy","31 ms","v0.2.4"],["Investigation","investigation:8082","healthy","42 ms","v0.3.0"],["Patrol","patrol:8083","degraded","186 ms","v0.2.2"],["Association","association:8084","healthy","27 ms","v0.2.1"],["Evolution","evolution:8085","healthy","38 ms","v0.2.0"],["Codex Builder","codex-builder:8086","healthy","54 ms","v0.1.8"],["Evaluator","evaluator:8087","healthy","33 ms","v0.2.3"],["Governance","governance:8088","healthy","24 ms","v0.2.1"],["Agent Gateway","agentgateway:3000","healthy","12 ms","v1.5.0"],["Environment DB","postgres:5432","healthy","8 ms","16.4"],["System DB","postgres:5432","healthy","9 ms","16.4"]
] as const;
