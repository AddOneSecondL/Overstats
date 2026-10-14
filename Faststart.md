# Overstats 快速开始

本文档用于说明如何为 `overstats` 准备最基本的大神凭据配置。

## 概览

`overstats` 至少需要在 [`overstats/config/config.py`](./config/config.py) 中配置一个大神账号：

```python
DASHEN_ACCOUNTS = [
    {
        "name": "primary",
        "role_id": 123456789,
        "token": "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
    }
]
```

开始之前，请先明确这两个字段的含义：

- `role_id`：大神侧账号标识，与已绑定的战网 / Battle.net 账号对应
- `token`：大神业务令牌，`overstats` 会用它访问上游接口

一般来说：

- `role_id` 对同一个已绑定账号通常比较稳定
- `token` 可能会过期，也可能会变化，但是时间很长

## 准备条件

开始前请确认：

- 你已经拥有网易大神账号
- 该大神账号已经绑定了目标战网 / Battle.net 账号
- 你可以正常登录大神网页，或者能打开大神内的相关活动页面
- 你知道如何通过 `F12` 打开浏览器开发者工具

## 第一步：登录大神

先登录大神账号：

- 大神官网：`https://ds.163.com/`

## 第二步：获取 `role_id`

`role_id` 可以从充值中心或者守望先锋官网拿到，这里以充值中心为例

推荐做法：

1. 打开充值中心，进入守望先锋页面，确认已经绑定好战网
2. 按 `F12` 打开开发者工具
3. 切换到 `Network` 标签页
4. 按 `Ctrl+F5` 强制刷新页面
5. 搜索 `&role_id`
6. 复制属于你账号的数字值

## 第三步：获取 `token`

目前最方便的方式，是直接复用页面上下文，让页面自己生成请求所需的签名字段。

在大神主页按下F12，打开浏览器控制台，然后粘贴运行下面这段脚本。

将下面代码中的 `YOUR_ROLE_ID` 替换成上一步拿到的 `role_id`。

```js
(async () => {
  const url = "https://inf.ds.163.com/v1/web/game/report/getReportToken";

  const payload = {
    appKey: "bn",
    roleId: "YOUR_ROLE_ID",
    server: "1",
    source: 1,
    type: "yearly",
  };

  function getCookie(name) {
    return (
      document.cookie
        .split("; ")
        .find((row) => row.startsWith(name + "="))
        ?.split("=")
        .slice(1)
        .join("=") || ""
    );
  }

  const body = JSON.stringify(payload);

  // 调用页面自身的签名模块生成请求签名
  const sigMod = await window.sig.default();
  const signRaw = sigMod.gen_sign(body);
  const signObj = JSON.parse(signRaw);

  const xsrf = getCookie("GL-XSRF-TOKEN");
  const uid = getCookie("GOD_UUID");
  const deviceId =
    localStorage.getItem("ns-client-id") ||
    localStorage.getItem("ds-website-uuid") ||
    "";

  console.log("body =", body);
  console.log("GL-CheckSum =", signObj.sign);
  console.log("GL-Nonce =", signObj.timestamp);
  console.log("GL-X-XSRF-TOKEN =", xsrf);
  console.log("GL-Uid =", uid);
  console.log("GL-DeviceId =", deviceId);

  const resp = await fetch(url, {
    method: "POST",
    credentials: "include",
    headers: {
      "Content-Type": "application/json;charset=UTF-8",
      "GL-ClientType": "61",
      "GL-DeviceId": deviceId,
      "GL-Uid": uid,
      "GL-X-XSRF-TOKEN": xsrf,
      "GL-CheckSum": signObj.sign,
      "GL-Nonce": String(signObj.timestamp),
    },
    body,
  });

  const text = await resp.text();

  console.log("status =", resp.status);
  console.log("raw =", text);

  try {
    const json = JSON.parse(text);
    console.log("json =", json);
    console.log("role_id =", json?.result?.roleId || payload.roleId);
    console.log("token =", json?.result?.token || "");
  } catch (e) {
    console.log("not json");
  }
})();
```

如果请求成功，通常会看到类似这样的返回：

```json
{
  "result": {
    "appKey": "bn",
    "roleId": "123456789",
    "server": "1",
    "day": "2026",
    "token": "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
  },
  "code": 200,
  "errmsg": "OK"
}
```

其中 `result.token` 就是你需要填入 `config.py` 的 `token`。

## 第四步：填写 `config.py`

拿到 `role_id` 和 `token` 之后，更新 [`overstats/config/config.py`](./config/config.py)：

```python
DASHEN_ACCOUNTS = [
    {
        "name": "primary",
        "role_id": 123456789,
        "token": "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
    }
]
```

如果你希望配置多个备用账号，也可以继续往 `DASHEN_ACCOUNTS` 里追加。

## 安全说明

以下内容都属于敏感信息：

- `token`
- 会话 Cookie
- XSRF 相关字段
- 请求签名字段

请不要：

- 提交到公开仓库
- 直接贴到公开 issue 或讨论区
- 在截图中不做遮挡就对外分享

如果这些内容已经泄露，建议立即退出登录并重新登录，使旧会话失效，然后重新获取凭据。
