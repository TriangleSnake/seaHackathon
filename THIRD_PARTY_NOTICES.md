# Third-Party Notices

This project uses or adapts the following third-party software and data. These
notices do not change the license of the project’s original source code.

## Cofacts LINE message fact-check dataset

- Dataset: `Cofacts/line-msg-fact-check-tw`
- Source: <https://huggingface.co/datasets/Cofacts/line-msg-fact-check-tw>
- License: [Creative Commons Attribution-ShareAlike 4.0 International](https://creativecommons.org/licenses/by-sa/4.0/)
- Additional terms: access to the gated dataset requires acceptance of the
  Cofacts Data User Agreement shown on the dataset page.
- Use in this repository: fictional messages in the Environment seed were
  selected and adapted from ecommerce scam themes in the Cofacts archive. The
  raw archive, original messages, user identifiers, phone numbers, account
  numbers, and original destinations are not redistributed by this repository.

Required attribution supplied by the Cofacts Working Group:

> 本編輯資料取自「Cofacts 真的假的」訊息回報機器人與查證協作社群，採
> CC BY-SA 4.0 授權提供。若欲補充資訊請訪問 Cofacts LINE bot
> <https://line.me/ti/p/@cofacts>

English attribution:

> This data by Cofacts message reporting chatbot and crowd-sourced fact-checking
> community is licensed under CC BY-SA 4.0. To provide more info, please visit
> Cofacts LINE bot <https://line.me/ti/p/@cofacts>.

The adapted Cofacts-derived seed content is offered under CC BY-SA 4.0. Changes
include fictionalization, removal of identifying information, replacement of
destinations with reserved domains, and adaptation to synthetic marketplace
scenarios.

## AgentGateway

- Project: `agentgateway/agentgateway`
- Version used: `v1.5.0`
- Container: `cr.agentgateway.dev/agentgateway:v1.5.0`
- Source: <https://github.com/agentgateway/agentgateway>
- License: [Apache License 2.0](https://github.com/agentgateway/agentgateway/blob/main/LICENSE)
- Use in this repository: the unmodified upstream container image is referenced
  by Docker Compose as the MCP gateway between agents and project-owned tools.

AgentGateway is an open-source Linux Foundation project. AgentGateway and its
authors do not endorse this project. The upstream license and notices continue
to apply to the distributed container image and upstream software.

## Project license status

No license has currently been declared for this repository’s original source
code. In the absence of a project license, no permission to copy, modify, or
redistribute that original source code is granted by default. The third-party
licenses above continue to apply to their respective software and data.
