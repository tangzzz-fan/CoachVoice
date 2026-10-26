# CoachVoice · 项目记忆

## 仓库

| 项 | 值 |
|---|---|
| 本地 | `/Users/tango/Developments/CoachVoice` |
| 远端 | <https://github.com/tangzzz-fan/CoachVoice>（**public**，`main`） |
| 账号 | `tangzzz-fan`（gh CLI 已登录，https 协议） |

**推送必须过用户的本地代理**，沙箱自带的白名单代理（50479）会拒掉 git 的 CONNECT 隧道（502）。
直连也不通（超时）。

```bash
env -u http_proxy -u https_proxy -u ALL_PROXY -u all_proxy \
    HTTPS_PROXY=http://127.0.0.1:7890 HTTP_PROXY=http://127.0.0.1:7890 \
    git -c http.version=HTTP/1.1 push
```

同一条命令要在沙箱外跑（`dangerouslyDisableSandbox: true`）。`gh` 的 API 调用可以走白名单，
只有 git 的 clone/push 需要这条。

## 台账是生成物

改 `scripts/build_phrase_bank.py` 里的 `SCENES` 数据，然后跑：

```bash
python3 scripts/build_phrase_bank.py          # 写 phrase-bank.json + 打表
python3 scripts/build_phrase_bank.py --check  # 只校验
```

**别手改 `phrase-bank.json`**，它是渲染脚本的输入，会漂。校验三条：字数 ≤16、文本唯一、三档齐全。

## 数字基线（引用用这些，别复用旧稿）

| 项 | 值 |
|---|---|
| 单句预算 | ≤4 秒 / **16 字**（4.0 字/秒 × 4s；旧稿写的 20 字会到 4.65 秒） |
| 情绪整句 | **120 条** = 20 场景 × 3 档 × 2 变体 |
| 总时长 / 体积 | 207 秒 / 0.79MB @AAC 32kbps |
| 现有片段 | 496 条（4 固定 + 43 动作名 + 150 要点 + ≈299 数字），**全部保持中性** |

## 两条不能破的规矩

1. **情绪只落在无变量的整句上。** 片段按 70ms 静音拼接，每段自带句尾，加档会把断点放大。
2. **档位选择必须确定性。** 事件强制档 + 会话基线档；变体轮转用会话种子，否则回放会变、A/B 失效。

## 人工阻塞

判据 3（三档像同一个人）需要 8–12 秒自录参考音 + 书面授权。预设音色（Qwen 的 Serena 等）
商用条款未核实，不能用作验收件。
