// Cifra los datos de la cartera para publicarlos en site/cartera.enc.json sin exponerlos.
// Uso:  CLAVE='frase secreta' node scripts/cifrar_cartera.mjs ruta/cartera.json [salida.json]
// El archivo de entrada (en claro) NUNCA se sube al repositorio; solo el resultado cifrado.
// Cifrado: PBKDF2-SHA256 (600.000 iteraciones) + AES-256-GCM, igual que lo descifra site/cartera.html.
import { webcrypto as C } from "node:crypto";
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const clave = process.env.CLAVE, entrada = process.argv[2];
if (!clave || !entrada) { console.error("Uso: CLAVE='frase' node scripts/cifrar_cartera.mjs cartera.json"); process.exit(1); }
const datos = JSON.parse(readFileSync(entrada, "utf8"));  // valida que sea JSON
const it = 600000, salt = C.getRandomValues(new Uint8Array(16)), iv = C.getRandomValues(new Uint8Array(12));
const base = await C.subtle.importKey("raw", new TextEncoder().encode(clave), "PBKDF2", false, ["deriveKey"]);
const key = await C.subtle.deriveKey({ name: "PBKDF2", hash: "SHA-256", salt, iterations: it }, base, { name: "AES-GCM", length: 256 }, false, ["encrypt"]);
const ct = await C.subtle.encrypt({ name: "AES-GCM", iv }, key, new TextEncoder().encode(JSON.stringify(datos)));
const b64 = u => Buffer.from(u).toString("base64");
const salida = process.argv[3] || join(dirname(fileURLToPath(import.meta.url)), "..", "site", "cartera.enc.json");
writeFileSync(salida, JSON.stringify({ v: 1, it, salt: b64(salt), iv: b64(iv), ct: b64(new Uint8Array(ct)) }));
console.log("Cifrado:", salida, `(${datos.pos?.length ?? "?"} posiciones)`);
