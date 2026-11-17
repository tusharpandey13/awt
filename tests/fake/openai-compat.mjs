import http from "node:http"; import fs from "node:fs";
// A fake OpenAI-compatible chat endpoint for local e2e tests: logs every request body, answers "OK summary". usage: node openai-compat.mjs LOGFILE PORT
const log = process.argv[2], port = Number(process.argv[3]);
http.createServer((req, res) => {
  let b = ""; req.on("data", d => b += d); req.on("end", () => {
    fs.appendFileSync(log, JSON.stringify({ url: req.url, body: b }) + "\n");
    let j = {}; try { j = JSON.parse(b) } catch {}
    if (!req.url.endsWith("/chat/completions")) { res.writeHead(404); return res.end("{}"); }
    const text = "OK summary", pt = Math.ceil(b.length / 4);
    if (j.stream) {
      res.writeHead(200, { "content-type": "text/event-stream" });
      const c = (d, f) => `data: ${JSON.stringify({ id: "x", object: "chat.completion.chunk", created: 1, model: "fake", choices: [{ index: 0, delta: d, finish_reason: f }] })}\n\n`;
      res.write(c({ role: "assistant", content: "" }, null)); res.write(c({ content: text }, null)); res.write(c({}, "stop"));
      res.write(`data: ${JSON.stringify({ id: "x", object: "chat.completion.chunk", created: 1, model: "fake", choices: [], usage: { prompt_tokens: pt, completion_tokens: 3, total_tokens: pt + 3 } })}\n\n`); res.end("data: [DONE]\n\n");
    } else { res.writeHead(200, { "content-type": "application/json" }); res.end(JSON.stringify({ id: "x", object: "chat.completion", created: 1, model: "fake", choices: [{ index: 0, message: { role: "assistant", content: text }, finish_reason: "stop" }], usage: { prompt_tokens: pt, completion_tokens: 3, total_tokens: pt + 3 } })); }
  });
}).listen(port, "127.0.0.1");
