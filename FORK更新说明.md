# Fork 更新说明

本仓库是在 `490720818/qq-pet-copilot` 基础上的个人 Fork。自定义修改保存在
`main` 分支，原仓库通过只读的 `upstream` 远程跟踪。

老手机可以在“设置”里把“慢速设备等待倍率”改为 `2`；程序会延长页面、按钮和
好友列表的加载重试窗口，已经加载成功的步骤不会被固定延时拖慢。

“雇佣好友名称”和“护理好友名称”都支持填写多个好友，使用中文或英文逗号分隔，
例如 `张三,李四,王五`。请给好友使用不会互相包含的唯一名称，程序会按顺序处理。

统计页额外记录冒险“提前召回”、雇佣成功和雇佣失败。雇佣成功后的工作会同时
计入打工次数与打工时长；旧数据若漏记时长，会按每次至少 10 分钟补齐。踩踩遍历
好友时只打印新发现的名字，不再反复输出整份累积名单。

好友竖向名单不再误等底部好友栏控件；进入好友家后才读取底部轮播。好友喂食/洗澡
会从所有列表候选中选择好友栏上方、屏幕中央的饼干或肥皂，避免把底部好友头像当成
护理道具。

自定义版 release 打包时会把更新地址指向本 Fork，因此程序内“检查更新”只会看到
本 Fork 发布的版本；上游更新仍按下述方式同步，避免误装上游原版覆盖自定义功能。

## 在 GitHub 网页同步

打开本 Fork 首页，点击 **Sync fork**，再点击 **Update branch**。没有冲突时，
GitHub 会直接把原仓库的新提交合并进来，自定义提交仍会保留。

## 在 Windows 本地同步

双击 `update_from_upstream.bat`。脚本只会执行普通合并，不会强制覆盖本地修改。
开始前需要保证工作区没有未提交的文件。

等价的手动命令：

```powershell
git remote add upstream https://github.com/490720818/qq-pet-copilot.git
git fetch upstream main
git switch main
git merge upstream/main
git push origin main
```

如果第一条命令提示 `upstream already exists`，可忽略并从第二条继续。

## 遇到冲突

出现 `CONFLICT` 时不要删除仓库，也不要使用 `git reset --hard`。冲突意味着原仓库
和本 Fork 修改了同一段代码；解决冲突、测试后再执行：

```powershell
git add -A
git commit
git push origin main
```

不确定如何选择时，把冲突提示交给 Codex 处理即可。
