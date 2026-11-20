## claude-foreman

- 預設自己做。只在這三種情況派子代理，並明寫 `model`：要讀或搜尋大量檔案（haiku）、長時間的執行和等待（haiku／sonnet）、
  對話已經很長又有一批規格明確的工作（sonnet）。
- 出貨前改到 `<例：src/data/ 的配方資料、存檔格式>` 時，用 `claude-foreman:verify` 做一次獨立驗證。
- 這個 repo 的檢查指令：`<例：npx tsc --noEmit>`、`<npm test>`、`<npx playwright test>`。
- 子代理不准動：`<例：package.json 的版本號、src/data/changelog.json>`；這些由主模型最後統一處理。
- 一個段落做完（推上去了、功能完成）而對話已經很長時，用一句話建議交接後開新 session。
