## 多模型派工（claude-foreman）

- 開始多檔案、多步驟的實作，批次修改，或長時間的執行等待之前，先載入 `claude-foreman:foreman` skill 過判斷關卡。
  單檔小修、快問快答、還在討論設計時不用。
- 派子代理時一律明寫 `model`；搜尋和盤點用 haiku，規格明確的實作用 sonnet。
- 這個 repo 的出貨檢查指令：`<例：npx tsc --noEmit>`、`<npm test>`、`<npx playwright test>`。
- worker 不准動：`<例：package.json 的版本號、src/data/changelog.json>`；這些由主模型最後統一處理。

<!-- 以下是給你自己的使用習慣，不是給模型的規則：
  日常步驟緊密相連的工作，用較便宜的模型當主模型，搭配 /advisor 讓強模型只在決策點出場
  （例：Sonnet 主做 + Opus advisor）。advisor 必須不弱於主模型；每次諮詢會重讀整份對話，
  長對話在階段之間先 /compact。 -->
