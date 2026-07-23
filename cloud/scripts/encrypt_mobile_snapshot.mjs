#!/usr/bin/env node

import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const runtimeData = process.env.APP_DATA_DIR
  || path.join(process.env.HOME, "Library/Application Support/A股趋势回调评分器/data");
const source = process.argv[2] || path.join(runtimeData, "mobile_snapshot.json");
const target = process.argv[3] || path.join(root, "mobile-site/public/data/mobile_snapshot.enc.json");
const passphrase = process.env.ASHARE_MOBILE_PASSPHRASE;

if (!passphrase || passphrase.length < 12) {
  throw new Error("ASHARE_MOBILE_PASSPHRASE must contain at least 12 characters");
}

const plaintext = fs.readFileSync(source);
const parsed = JSON.parse(plaintext.toString("utf8"));
if (!parsed.ok || !parsed.watchlist?.items?.length || !parsed.updatedAt) {
  throw new Error("mobile snapshot is incomplete");
}

const sourceDigest = crypto.createHash("sha256").update(plaintext).digest("hex");
if (fs.existsSync(target)) {
  try {
    const current = JSON.parse(fs.readFileSync(target, "utf8"));
    if (current.sourceDigest === sourceDigest) {
      console.log(JSON.stringify({
        ok: true,
        unchanged: true,
        updatedAt: parsed.updatedAt,
        watchlistCount: parsed.watchlist.items.length,
        target,
      }));
      process.exit(0);
    }
  } catch {
    // Replace malformed or legacy encrypted payloads below.
  }
}

const salt = crypto.randomBytes(16);
const iv = crypto.randomBytes(12);
const iterations = 310000;
const key = crypto.pbkdf2Sync(passphrase, salt, iterations, 32, "sha256");
const cipher = crypto.createCipheriv("aes-256-gcm", key, iv);
const encrypted = Buffer.concat([cipher.update(plaintext), cipher.final()]);
const authTag = cipher.getAuthTag();
const payload = {
  version: 1,
  algorithm: "AES-256-GCM",
  kdf: "PBKDF2-SHA256",
  iterations,
  salt: salt.toString("base64"),
  iv: iv.toString("base64"),
  ciphertext: Buffer.concat([encrypted, authTag]).toString("base64"),
  sourceDigest,
  updatedAt: parsed.updatedAt,
  watchlistCount: parsed.watchlist.items.length,
};

fs.mkdirSync(path.dirname(target), { recursive: true });
const temporary = `${target}.tmp`;
fs.writeFileSync(temporary, JSON.stringify(payload));
fs.renameSync(temporary, target);
console.log(JSON.stringify({
  ok: true,
  updatedAt: payload.updatedAt,
  watchlistCount: payload.watchlistCount,
  target,
}));
