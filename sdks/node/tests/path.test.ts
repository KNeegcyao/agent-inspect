// 注入路径补丁测试:嵌套对象 / 数组下标 / 混合路径(spec js-sdk 注入修改)。
import { assert, describe, it } from "./helpers.js";
import { setPath, splitKeyPath } from "../src/interceptor.js";

describe("input path patch", () => {
  it("splits dotted and bracket segments", () => {
    assert.deepEqual(splitKeyPath("messages[0].content"), ["messages", 0, "content"]);
    assert.deepEqual(splitKeyPath("params.temperature"), ["params", "temperature"]);
    assert.deepEqual(splitKeyPath("plain"), ["plain"]);
  });

  it("patches nested dict path", () => {
    const obj: Record<string, unknown> = { params: { temperature: 0.1 } };
    setPath(obj, ["params", "temperature"], 0.9);
    assert.deepEqual(obj, { params: { temperature: 0.9 } });
  });

  it("patches array index and creates missing containers", () => {
    const obj: Record<string, unknown> = { messages: [{ role: "user", content: "hi" }] };
    setPath(obj, ["messages", 0, "content"], "EDITED");
    assert.deepEqual(obj, { messages: [{ role: "user", content: "EDITED" }] });

    const empty: Record<string, unknown> = {};
    setPath(empty, ["a", 1, "b"], 7);
    assert.deepEqual((empty["a"] as unknown[])[1], { b: 7 });
  });
});
