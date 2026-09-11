const express = require("express");
const path = require("path");
const http = require("http");

const app = express();
const port = process.env.PORT || 2513;
const rootDir = __dirname;

app.use(express.static(rootDir));

app.get("/health", (_req, res) => {
  res.json({ status: "ok" });
});

app.get(["/", "/transactions"], (_req, res) => {
  res.sendFile(path.join(rootDir, "index.html"));
});

app.get("/strategy", (_req, res) => {
  res.sendFile(path.join(rootDir, "strategy.html"));
});

app.get("/simulations", (_req, res) => {
  res.sendFile(path.join(rootDir, "simulations.html"));
});

// Proxy API requests to the backend
app.use(/^\/api\/.*/, (req, res) => {
  const backendUrl = `http://wes_get_rich_backend:2512${req.url}`;
  const options = {
    method: req.method,
    headers: req.headers,
  };

  const backendReq = http.request(backendUrl, options, (backendRes) => {
    res.writeHead(backendRes.statusCode, backendRes.headers);
    backendRes.pipe(res);
  });

  req.pipe(backendReq);
});

app.get("*", (_req, res) => {
  res.sendFile(path.join(rootDir, "index.html"));
});

app.listen(port, () => {
  console.log(`Frontend listening on port ${port}`);
});
