# claude-foreman

給 Claude Code 用的多模型派工 skill。強模型（Opus／Fable）當工頭：拆工作、把可切塊的部分派給較便宜的模型
（Sonnet／Haiku）、親自驗收、整合，最後留下一行成本紀錄。

它處理三件事：

1. **該不該派工**：先試著把任務寫成單元。寫得出兩個以上能各自驗證的單元才派，否則自己做。
2. **派得好不好**：固定的交接說明、固定格式的回報、主模型親自重跑檢查、失敗先分類再決定要不要升級模型。
3. **到底有沒有用**：每次執行都記帳，事後回填「實際用過之後發現幾個問題」，累積幾次後回顧。

## 安裝

```
/plugin marketplace add EndeavorYen/claude-foreman
/plugin install claude-foreman@claude-foreman
```

需要 Python 3.9 以上（只用標準庫），Windows、macOS、Linux 都能跑。

想讓它更穩定地自動啟用，把 [`snippets/CLAUDE.md`](snippets/CLAUDE.md) 貼進各 repo 的 CLAUDE.md 並填上該 repo 的檢查指令。
手動啟用：`/claude-foreman:foreman`。

## 流程

```
任務 → 判斷關卡（先拆再判）→ 自己做
                          → 派工：貼計畫表 → 交接說明 → 派出 → 檢查回報
                                  → 關卡 1（主模型重跑檢查）→ 關卡 2（依風險派驗證者）
                                  → 整合 → 出貨關卡（repo 自己的規則）→ 成本行
```

| 層 | 模型 | 給它做 |
|---|---|---|
| T0 | haiku | 搜尋、盤點、機械修改、跑指令、依標準核對 |
| T1 | sonnet | 規格明確的實作、寫測試、根因已知的修正 |
| T2 | opus | 跨檔重構、找根因、存檔與安全相關 |
| 主模型 | opus／fable | 規劃、分派、驗收、整合 |

完整規則在 [`skills/foreman/SKILL.md`](skills/foreman/SKILL.md)。

## 帳本工具

`skills/foreman/scripts/foreman.py` 負責記帳，也負責擋下違規的動作。寫在文字裡的規則容易被模型略過，
所以重要的幾條做成指令會拒絕：

| 規則 | 怎麼擋 |
|---|---|
| PASS 要有證據；寫了測試不等於跑過 | `report` 檢查回報，不合格 exit 3 |
| worker 不能動範圍外的檔案 | `report` 比對 `plan add --files` |
| 不採信 worker 自己說的結果 | `dispatch close --result PASS` 之前必須有主模型在回報之後跑的 `gate` |
| 每個單元最多派 3 次 | 第 4 次 `dispatch open` 被拒絕 |
| 失敗要先分類 | `dispatch close --result FAIL` 必須帶 `--fail-kind` |
| 有依賴的單元要等前一個整合完 | `dispatch open` 檢查 |
| 計畫寫了要驗證者，就不能跳過 | `unit set integrated` 檢查 |
| 收尾前要跑過 repo 的完整檢查 | `finish` 檢查有沒有 `gate ship` |
| 要知道子代理實際跑在哪個模型 | 回報必填 `model`；跟指定的不符時警告，成本行依實際模型分組 |
| 單元要有自己的工作目錄 | `worktree U2` 從基準開、連好相依套件；`gate U2` 預設在那裡跑，在 worktree 裡也找得到同一本帳 |

plugin 另外附三種精簡的子代理類型（`worker`、`verifier`、`scout`），只帶讀寫檔和 shell，用來壓低每次派遣的固定開銷。

紀錄放在各 repo 的 `.claude/foreman-runs/`（自動加進 `.git/info/exclude`，不會進版控）：

```
python skills/foreman/scripts/foreman.py review            # 歷次執行的表格
python skills/foreman/scripts/foreman.py feedback <run> --issues 1   # 回填事後發現的問題數
```

## 目前的限制

- 只在能指定子代理模型的環境有用（Claude Code）。不能指定時 skill 會改成自己做。
- 成本行只包含量得到的數字：子代理的派遣次數、token、時間。主模型自己用了多少、相較於單一模型省了多少，
  都不在裡面；後者沒有對照組算不出來。
- 小任務派工的固定開銷可能比省下的多。判斷關卡的目的就是把這類任務留給主模型自己做。
- 「由下往上」的做法（便宜模型主做、強模型當 advisor）是 Claude Code 內建的 `/advisor`，不在這個 skill 的範圍，
  使用建議寫在 `snippets/CLAUDE.md` 的註解裡。

## 開發

```
python -m unittest discover tests
```

設計上借用了 [midego1/claude-orchestrate](https://github.com/midego1/claude-orchestrate) 的幾個想法：
規則要用工具強制、證據門檻、失敗分類、重試上限。實作是重新寫的，沒有沿用它的程式碼。
