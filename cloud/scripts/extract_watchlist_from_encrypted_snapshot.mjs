#!/usr/bin/env node

import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import process from "node:process";

const source = process.argv[2];
const target = process.argv[3];
const passphrase = process.env.ASHARE_MOBILE_PASSPHRASE;

if (!source || !target) {
  throw new Error("usage: extract_watchlist_from_encrypted_snapshot.mjs <source> <target>");
}
if (!passphrase || passphrase.length < 12) {
  throw new Error("ASHARE_MOBILE_PASSPHRASE must contain at least 12 characters");
}

const payload = JSON.parse(fs.readFileSync(source, "utf8"));
if (
  payload.version !== 1
  || payload.algorithm !== "AES-256-GCM"
  || payload.kdf !== "PBKDF2-SHA256"
) {
  throw new Error("unsupported encrypted snapshot format");
}

const salt = Buffer.from(payload.salt, "base64");
const iv = Buffer.from(payload.iv, "base64");
const combined = Buffer.from(payload.ciphertext, "base64");
const authTag = combined.subarray(combined.length - 16);
const ciphertext = combined.subarray(0, combined.length - 16);
const key = crypto.pbkdf2Sync(
  passphrase,
  salt,
  payload.iterations,
  32,
  "sha256",
);
const decipher = crypto.createDecipheriv("aes-256-gcm", key, iv);
decipher.setAuthTag(authTag);
const plaintext = Buffer.concat([
  decipher.update(ciphertext),
  decipher.final(),
]);
const snapshot = JSON.parse(plaintext.toString("utf8"));
const items = snapshot?.watchlist?.items;
if (!Array.isArray(items) || items.length === 0) {
  throw new Error("encrypted snapshot contains no watchlist items");
}

fs.mkdirSync(path.dirname(target), { recursive: true });
const temporary = `${target}.tmp`;
fs.writeFileSync(
  temporary,
  JSON.stringify({ items }, null, 2),
  { encoding: "utf8", mode: 0o600 },
);
fs.renameSync(temporary, target);
console.log(JSON.stringify({ ok: true, watchlistCount: items.length }));
