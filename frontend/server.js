const express = require("express");
const path = require("path");

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

app.get("*", (_req, res) => {
  res.sendFile(path.join(rootDir, "index.html"));
});

app.listen(port, () => {
  console.log(`Frontend listening on port ${port}`);
});
