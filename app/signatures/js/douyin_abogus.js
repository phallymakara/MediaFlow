/* Minimal a_bogus generator. Structure: UA sample -> md5 -> RC4 -> custom b64. */
const _T = [
  0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,
  0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,
  0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,
  0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00
];

const _M = "Dkdpgh4ZKsQB80/Mfvw36XI1R25-WUAlEi7NLboqYTOPuzmFjJnryx9HVGSaV6t3c8JXY2fKr5gQeBwIhPlRMNyCvU$djS";

function _rc4(key, data) {
  const s = [], k = [];
  for (let i = 0; i < 256; i++) { s[i] = i; k[i] = key.charCodeAt(i % key.length); }
  let j = 0;
  for (let i = 0; i < 256; i++) {
    j = (j + s[i] + k[i]) & 0xff;
    [s[i], s[j]] = [s[j], s[i]];
  }
  let i = 0; j = 0; const out = [];
  for (let n = 0; n < data.length; n++) {
    i = (i + 1) & 0xff; j = (j + s[i]) & 0xff;
    [s[i], s[j]] = [s[j], s[i]];
    out.push(data[n] ^ s[(s[i] + s[j]) & 0xff]);
  }
  return out;
}

function _b64(bytes) {
  let out = "";
  for (let i = 0; i < bytes.length; i += 3) {
    const b0 = bytes[i], b1 = bytes[i+1], b2 = bytes[i+2];
    out += _M[b0 >> 2];
    out += _M[((b0 & 3) << 4) | ((b1 ?? 0) >> 4)];
    if (b1 !== undefined) out += _M[((b1 & 15) << 2) | ((b2 ?? 0) >> 6)];
    if (b2 !== undefined) out += _M[b2 & 63];
  }
  return out;
}

function _md5Bytes(str) {
  // compact md5 over UTF-8 bytes, returns byte array
  const b = [];
  for (const ch of str) {
    let c = ch.codePointAt(0);
    if (c < 0x80) b.push(c);
    else if (c < 0x800) b.push(0xc0 | (c >> 6), 0x80 | (c & 63));
    else b.push(0xe0 | (c >> 12), 0x80 | ((c >> 6) & 63), 0x80 | (c & 63));
  }
  const ml = b.length * 8;
  b.push(0x80);
  while (b.length % 64 !== 56) b.push(0);
  for (let i = 0; i < 8; i++) b.push((ml >>> (8 * i)) & 0xff);

  let a0 = 0x67452301, b0 = 0xefcdab89, c0 = 0x98badcfe, d0 = 0x10325476;
  const S = [7,12,17,22,5,9,14,20,4,11,16,23,6,10,15,21];
  const K = [];
  for (let i = 0; i < 64; i++) K[i] = (Math.abs(Math.sin(i + 1)) * 2 ** 32) | 0;

  for (let off = 0; off < b.length; off += 64) {
    const w = [];
    for (let i = 0; i < 16; i++)
      w[i] = b[off+i*4] | (b[off+i*4+1] << 8) | (b[off+i*4+2] << 16) | (b[off+i*4+3] << 24);
    let [A,B,C,D] = [a0,b0,c0,d0];
    for (let i = 0; i < 64; i++) {
      let f, g;
      if (i < 16)      { f = (B & C) | (~B & D);           g = i; }
      else if (i < 32) { f = (D & B) | (~D & C);           g = (5*i + 1) % 16; }
      else if (i < 48) { f = B ^ C ^ D;                    g = (3*i + 5) % 16; }
      else             { f = C ^ (B | ~D);                 g = (7*i) % 16; }
      const tmp = D;
      D = C; C = B;
      const x = (A + f + K[i] + w[g]) | 0;
      const s = S[(i >> 4) * 4 + (i % 4)];
      B = (B + ((x << s) | (x >>> (32 - s)))) | 0;
      A = tmp;
    }
    a0 = (a0 + A) | 0; b0 = (b0 + B) | 0; c0 = (c0 + C) | 0; d0 = (d0 + D) | 0;
  }
  const out = [];
  for (const v of [a0,b0,c0,d0])
    for (let i = 0; i < 4; i++) out.push((v >>> (8 * i)) & 0xff);
  return out;
}

function getABogus(query, ua) {
  const ts = Math.floor(Date.now() / 1000);
  const seed = `${ua}|${ts}|${query}|cus|sck|1|0|0|0|`;
  const digest = _md5Bytes(seed);
  const stream = _rc4("dhzx" + ua.slice(0, 16), digest.concat([0, 0, 0, 0]));
  const tail = _b64(stream);
  const head = _b64(_md5Bytes(query + ts).slice(0, 4));
  return (head + tail).replace(/=+$/, "");
}

