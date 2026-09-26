(function () {
  "use strict";

  var enc = new TextEncoder();
  var dec = new TextDecoder();
  var PREFIX = "pt1:";
  var INVITE_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ";
  var INVITE_AAD = enc.encode("parenting-together-invite-v1");

  function b64(bytes) {
    var value = "";
    bytes = new Uint8Array(bytes);
    for (var i = 0; i < bytes.length; i += 1) value += String.fromCharCode(bytes[i]);
    return btoa(value).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  }

  function unb64(value) {
    value = value.replace(/-/g, "+").replace(/_/g, "/");
    while (value.length % 4) value += "=";
    var raw = atob(value), out = new Uint8Array(raw.length);
    for (var i = 0; i < raw.length; i += 1) out[i] = raw.charCodeAt(i);
    return out;
  }

  function randomBytes(length) {
    return crypto.getRandomValues(new Uint8Array(length));
  }

  function joinBytes(first, second) {
    var output = new Uint8Array(first.length + second.length);
    output.set(first, 0);
    output.set(second, first.length);
    return output;
  }

  function encodeInviteSecret(bytes) {
    var output = "", buffer = 0, bits = 0;
    for (var i = 0; i < bytes.length; i += 1) {
      buffer = (buffer << 8) | bytes[i];
      bits += 8;
      while (bits >= 5) {
        bits -= 5;
        output += INVITE_ALPHABET[(buffer >>> bits) & 31];
      }
      buffer &= (1 << bits) - 1;
    }
    if (bits) output += INVITE_ALPHABET[(buffer << (5 - bits)) & 31];
    return output.match(/.{1,4}/g).join("-");
  }

  function decodeInviteSecret(code) {
    var compact = String(code || "").toUpperCase().replace(/[\s-]/g, "");
    if (compact.length !== 24) throw new Error("Enter the complete 24-character invite code.");
    var output = [], buffer = 0, bits = 0;
    for (var i = 0; i < compact.length; i += 1) {
      var value = INVITE_ALPHABET.indexOf(compact[i]);
      if (value < 0) throw new Error("That invite code contains an invalid character.");
      buffer = (buffer << 5) | value;
      bits += 5;
      if (bits >= 8) {
        bits -= 8;
        output.push((buffer >>> bits) & 255);
        buffer &= (1 << bits) - 1;
      }
    }
    if (output.length !== 15) throw new Error("That invite code is not valid.");
    return new Uint8Array(output);
  }

  async function inviteMaterial(codeOrSecret) {
    var secret = typeof codeOrSecret === "string" ? decodeInviteSecret(codeOrSecret) : codeOrSecret;
    var lookup = await crypto.subtle.digest("SHA-256", joinBytes(enc.encode("lookup:"), secret));
    var keyBytes = await crypto.subtle.digest("SHA-256", joinBytes(enc.encode("key:"), secret));
    var key = await crypto.subtle.importKey("raw", keyBytes, {name:"AES-GCM"}, false, ["encrypt", "decrypt"]);
    return {lookup:b64(lookup), key:key};
  }

  function recoveryCode() {
    var parts = [];
    while (parts.length < 16) {
      var values = new Uint16Array(32);
      crypto.getRandomValues(values);
      for (var i = 0; i < values.length && parts.length < 16; i += 1) {
        if (values[i] < 65000) parts.push(String(values[i] % 1000).padStart(3, "0"));
      }
    }
    return parts.join(" ");
  }

  function normaliseCode(value) {
    return String(value || "").replace(/\D/g, "");
  }

  async function recoveryKey(code, salt) {
    if (normaliseCode(code).length !== 48) throw new Error("Enter all 16 recovery phrase groups.");
    var material = await crypto.subtle.importKey("raw", enc.encode(normaliseCode(code)), "PBKDF2", false, ["deriveKey"]);
    return crypto.subtle.deriveKey(
      {name:"PBKDF2", salt:salt, iterations:600000, hash:"SHA-256"}, material,
      {name:"AES-GCM", length:256}, false, ["encrypt", "decrypt"]
    );
  }

  async function wrap(raw, code) {
    var salt = randomBytes(16), iv = randomBytes(12), key = await recoveryKey(code, salt);
    var data = await crypto.subtle.encrypt({name:"AES-GCM", iv:iv}, key, raw);
    return {v:1, kdf:"PBKDF2-SHA256", iterations:600000, salt:b64(salt), iv:b64(iv), data:b64(data)};
  }

  async function unwrap(envelope, code) {
    try {
      var key = await recoveryKey(code, unb64(envelope.salt));
      return new Uint8Array(await crypto.subtle.decrypt(
        {name:"AES-GCM", iv:unb64(envelope.iv)}, key, unb64(envelope.data)
      ));
    } catch (error) {
      throw new Error("That recovery phrase is not correct.");
    }
  }

  function openDb() {
    return new Promise(function (resolve, reject) {
      var request = indexedDB.open("parenting-together-vault", 1);
      request.onupgradeneeded = function () { request.result.createObjectStore("keys"); };
      request.onsuccess = function () { resolve(request.result); };
      request.onerror = function () { reject(request.error); };
    });
  }

  async function storedValue(name) {
    var database = await openDb();
    return new Promise(function (resolve, reject) {
      var request = database.transaction("keys").objectStore("keys").get(name);
      request.onsuccess = function () { resolve(request.result); };
      request.onerror = function () { reject(request.error); };
    });
  }

  async function storeValue(name, value) {
    var database = await openDb();
    return new Promise(function (resolve, reject) {
      var request = database.transaction("keys", "readwrite").objectStore("keys").put(value, name);
      request.onsuccess = resolve;
      request.onerror = function () { reject(request.error); };
    });
  }

  async function deviceKey(userId) {
    var existing = await storedValue("device:" + userId);
    if (existing) return existing;
    var created = await crypto.subtle.generateKey({name:"AES-GCM", length:256}, false, ["encrypt", "decrypt"]);
    await storeValue("device:" + userId, created);
    return created;
  }

  async function remember(userId, raw) {
    var key = await deviceKey(userId), iv = randomBytes(12);
    var data = await crypto.subtle.encrypt({name:"AES-GCM", iv:iv}, key, raw);
    var saved = {v:1, iv:b64(iv), data:b64(data)};
    await storeValue("vault:" + userId, saved);
    localStorage.setItem("pt-vault-" + userId, JSON.stringify(saved));
    if (typeof navigator !== "undefined" && navigator.storage && navigator.storage.persist) {
      try { await navigator.storage.persist(); } catch (_) {}
    }
  }

  async function remembered(userId) {
    var saved = await storedValue("vault:" + userId), fromLocal = false;
    if (!saved) {
      try { saved = JSON.parse(localStorage.getItem("pt-vault-" + userId)); fromLocal = Boolean(saved); } catch (_) { return null; }
    }
    if (!saved) return null;
    try {
      var key = await deviceKey(userId);
      var raw = new Uint8Array(await crypto.subtle.decrypt({name:"AES-GCM", iv:unb64(saved.iv)}, key, unb64(saved.data)));
      if (fromLocal) await storeValue("vault:" + userId, saved);
      return raw;
    } catch (_) {
      localStorage.removeItem("pt-vault-" + userId);
      return null;
    }
  }

  async function vaultFromRaw(raw) {
    var key = await crypto.subtle.importKey("raw", raw, {name:"AES-GCM"}, true, ["encrypt", "decrypt"]);
    return {
      raw: raw,
      encrypt: async function (value) {
        if (value == null || value === "" || String(value).startsWith(PREFIX)) return value;
        var iv = randomBytes(12);
        var data = await crypto.subtle.encrypt({name:"AES-GCM", iv:iv}, key, enc.encode(String(value)));
        return PREFIX + b64(iv) + ":" + b64(data);
      },
      decrypt: async function (value) {
        if (typeof value !== "string" || !value.startsWith(PREFIX)) return value;
        var parts = value.split(":");
        try {
          return dec.decode(await crypto.subtle.decrypt({name:"AES-GCM", iv:unb64(parts[1])}, key, unb64(parts[2])));
        } catch (_) {
          return "[Locked encrypted data]";
        }
      },
      encryptFile: async function (file) {
        var iv=randomBytes(12), data=await crypto.subtle.encrypt({name:"AES-GCM",iv:iv},key,await file.arrayBuffer());
        return new Blob([enc.encode("PTF1"),iv,new Uint8Array(data)],{type:"application/octet-stream"});
      },
      decryptFile: async function (buffer) {
        var bytes=new Uint8Array(buffer);
        if(dec.decode(bytes.slice(0,4))!=="PTF1")throw new Error("This receipt is not encrypted.");
        return crypto.subtle.decrypt({name:"AES-GCM",iv:bytes.slice(4,16)},key,bytes.slice(16));
      },
      export: function () { return b64(raw); }
    };
  }

  async function create() {
    var raw = randomBytes(32), code = recoveryCode();
    return {vault:await vaultFromRaw(raw), code:code, envelope:await wrap(raw, code)};
  }

  async function load(userId) {
    var raw = await remembered(userId);
    return raw ? vaultFromRaw(raw) : null;
  }

  async function unlock(userId, envelope, code) {
    var raw = await unwrap(envelope, code);
    await remember(userId, raw);
    return vaultFromRaw(raw);
  }

  async function createInvite(vault) {
    var secret = randomBytes(15), material = await inviteMaterial(secret), iv = randomBytes(12);
    var data = await crypto.subtle.encrypt(
      {name:"AES-GCM", iv:iv, additionalData:INVITE_AAD}, material.key, vault.raw
    );
    return {code:encodeInviteSecret(secret), lookup:material.lookup,
      payload:{v:1, iv:b64(iv), data:b64(data)}};
  }

  async function inviteLookup(code) {
    return (await inviteMaterial(code)).lookup;
  }

  async function acceptInvite(code, payload) {
    if (!payload || payload.v !== 1 || !payload.iv || !payload.data) throw new Error("This secure invite is invalid.");
    var material = await inviteMaterial(code), raw;
    try {
      raw = new Uint8Array(await crypto.subtle.decrypt(
        {name:"AES-GCM", iv:unb64(payload.iv), additionalData:INVITE_AAD}, material.key, unb64(payload.data)
      ));
    } catch (_) {
      throw new Error("That invite code is incorrect or has expired.");
    }
    if (raw.length !== 32) throw new Error("This secure invite is invalid.");
    var recovery = recoveryCode(), envelope = await wrap(raw, recovery);
    return {vault:await vaultFromRaw(raw), code:recovery, envelope:envelope};
  }

  async function rememberVault(userId, vault) { await remember(userId, vault.raw); }

  window.PTVault = {create:create, load:load, unlock:unlock, createInvite:createInvite,
    inviteLookup:inviteLookup, acceptInvite:acceptInvite, remember:rememberVault, prefix:PREFIX};
}());
