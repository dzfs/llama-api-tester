定位是 ollma 的多端点管理测试工具。
如果是对单端点的使用，请选择 Cheery-Studio 等更好的专业 LLM Client。

usage: 根目录创建 `srv_list.txt`，填入 llama 服务器地址，每行一个，带不带 `http://` 都可以。然后运行 `python main.py` 即可。

功能：
1. 初始化并发检查和清除无效服务器


备用：
1. 提取 ip 端口的正则： `^(?:.*?)(?:https?://)?(\d{1,3}(?:\.\d{1,3}){3}:\d+).*` -> `$1`