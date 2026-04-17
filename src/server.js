#!/usr/bin/env node
/**
 * Frank Personal Voice Agent - Phase 1 MVP Server
 * 
 * 安全增强版：请求体限制 + 全局超时 + CORS 收紧 + 环境变量校验
 */
import http from 'http';
import url from 'url';
import { Readable } from 'stream';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PORT = process.env.PORT || 3000;

// ── 安全常量 ──────────────────────────────────────────────
const MAX_JSON_BODY   = 64  * 1024;   // /api/chat, /api/tts: 64 KB
const MAX_AUDIO_BODY  = 10  * 1024 * 1024; // /api/voice: 10 MB
const REQUEST_TIMEOUT = 30_000;        // 全局请求超时 30s
const ALLOWED_ORIGINS = (process.env.ALLOWED_ORIGINS || '').split(',').filter(Boolean);

// ── 环境变量校验 ──────────────────────────────────────────
const CONFIG = {
  DASHSCOPE_API_KEY: process.env.DASHSCOPE_API_KEY || '',
  MINIMAX_API_KEY:   process.env.MINIMAX_API_KEY   || '',
  MINIMAX_VOICE_ID:  process.env.MINIMAX_VOICE_ID  || 'male-shaun',
  OPENAI_API_KEY:    process.env.OPENAI_API_KEY    || '',
  SERVER_URL:        process.env.SERVER_URL         || `http://localhost:${PORT}`,
};

function validateEnv() {
  const missing = [];
  if (!CONFIG.DASHSCOPE_API_KEY) missing.push('DASHSCOPE_API_KEY');
  if (!CONFIG.MINIMAX_API_KEY)   missing.push('MINIMAX_API_KEY');

  if (missing.length > 0) {
    console.warn(`\n⚠️  [启动警告] 以下核心 API Key 未配置，相关功能将不可用：`);
    missing.forEach(k => console.warn(`   - ${k}`));
    console.warn('   请通过 .env 文件或环境变量设置后重启。\n');
  }
  if (!CONFIG.OPENAI_API_KEY) {
    console.info('ℹ️  [提示] OPENAI_API_KEY 未配置，Whisper STT 降级不可用（可选）。');
  }
}

// ── 工具函数 ──────────────────────────────────────────────

/**
 * 从请求流中安全读取 body，支持体积上限和中途熔断。
 * 使用 Buffer[] 拼接代替 string += chunk，效率更高。
 * @param {http.IncomingMessage} req
 * @param {number} maxBytes
 * @returns {Promise<Buffer>}
 */
function readBody(req, maxBytes) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    let totalBytes = 0;

    req.on('data', (chunk) => {
      totalBytes += chunk.length;
      if (totalBytes > maxBytes) {
        req.destroy();
        reject(new PayloadTooLargeError(maxBytes));
        return;
      }
      chunks.push(chunk);
    });
    req.on('end',   () => resolve(Buffer.concat(chunks)));
    req.on('error', (err) => reject(err));
  });
}

class PayloadTooLargeError extends Error {
  constructor(limit) {
    super(`请求体超过上限 (${(limit / 1024).toFixed(0)} KB)`);
    this.statusCode = 413;
  }
}

/**
 * 带超时的 fetch 封装
 */
async function fetchWithTimeout(url, options = {}, timeoutMs = REQUEST_TIMEOUT) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(url, { ...options, signal: controller.signal });
    return res;
  } finally {
    clearTimeout(timer);
  }
}

/**
 * CORS 处理：生产环境白名单模式，开发环境宽松模式
 */
function setCorsHeaders(req, res) {
  const origin = req.headers.origin || '*';
  if (ALLOWED_ORIGINS.length > 0) {
    // 生产模式：仅允许白名单域名
    if (ALLOWED_ORIGINS.includes(origin)) {
      res.setHeader('Access-Control-Allow-Origin', origin);
    }
    // 不在白名单中的请求不设置 CORS header，浏览器会自动拦截
  } else {
    // 开发模式：允许所有来源
    res.setHeader('Access-Control-Allow-Origin', '*');
  }
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
  res.setHeader('Access-Control-Expose-Headers', 'X-Reply-Text');
}

// ── 业务逻辑 ──────────────────────────────────────────────

async function callDashScope(text, context = []) {
  const messages = [
    {
      role: 'system',
      content: `你是 Frank 的私人语音助手，名叫小Ops。
说话简洁、口语化、亲切
理解 Frank 的表达习惯（口语化、跳跃式思维）
场景感知：若Frank提到"开会"、"跑步"、"开车"，自动适配表达风格
回复不宜过长，重点突出`
    },
    ...context,
    { role: 'user', content: text }
  ];
  const response = await fetchWithTimeout('https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions', {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${CONFIG.DASHSCOPE_API_KEY}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      model: 'qwen3.5-flash',
      messages,
      max_tokens: 500,
      temperature: 0.7,
    })
  });
  if (!response.ok) {
    const err = await response.text();
    throw new Error(`DashScope API error: ${response.status} - ${err}`);
  }
  const data = await response.json();
  return data.choices[0].message.content;
}

async function callMiniMaxTTS(text) {
  const response = await fetchWithTimeout('https://api.minimaxi.com/v1/t2a_v2', {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${CONFIG.MINIMAX_API_KEY}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      model: 'speech-2.8-turbo',
      text,
      voice_setting: {
        voice_id: CONFIG.MINIMAX_VOICE_ID,
        speed: 1.0,
        volume: 1.0,
        pitch: 0
      },
      audio_setting: {
        audio_format: 'mp3',
        sample_rate: 32000,
        bitrate: 128000
      }
    })
  });
  if (!response.ok) {
    const err = await response.text();
    throw new Error(`MiniMax TTS API error: ${response.status} - ${err}`);
  }
  return await response.arrayBuffer();
}

async function transcribeWithWhisper(audioBuffer) {
  const formData = new FormData();
  const blob = new Blob([audioBuffer], { type: 'audio/webm' });
  formData.append('file', blob, 'audio.webm');
  formData.append('model', 'whisper-1');
  formData.append('language', 'zh');
  const response = await fetchWithTimeout('https://api.openai.com/v1/audio/transcriptions', {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${CONFIG.OPENAI_API_KEY}`,
    },
    body: formData
  });
  if (!response.ok) throw new Error(`Whisper API error: ${response.status}`);
  const data = await response.json();
  return data.text;
}

// ── 静态文件 MIME ─────────────────────────────────────────

const MIME_TYPES = {
  '.html': 'text/html; charset=utf-8',
  '.js':   'application/javascript; charset=utf-8',
  '.css':  'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.png':  'image/png',
  '.ico':  'image/x-icon',
};

// ── HTTP 服务器 ──────────────────────────────────────────

const server = http.createServer(async (req, res) => {
  // 全局请求超时保护
  req.setTimeout(REQUEST_TIMEOUT, () => {
    res.writeHead(408, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ error: '请求超时' }));
    req.destroy();
  });

  const parsedUrl = url.parse(req.url, true);
  const pathname = parsedUrl.pathname;

  setCorsHeaders(req, res);

  if (req.method === 'OPTIONS') {
    res.writeHead(204);
    res.end();
    return;
  }

  try {
    // ── 首页 ──
    if (pathname === '/' && req.method === 'GET') {
      const filePath = path.join(__dirname, '../public/index.html');
      res.writeHead(200, { 'Content-Type': MIME_TYPES['.html'] });
      fs.createReadStream(filePath).pipe(res);
      return;
    }

    // ── /api/chat（文字对话）──
    if (pathname === '/api/chat' && req.method === 'POST') {
      const rawBody = await readBody(req, MAX_JSON_BODY);
      const { text, history = [] } = JSON.parse(rawBody.toString('utf-8'));
      if (!text) {
        res.writeHead(400, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ error: 'text is required' }));
        return;
      }
      const reply = await callDashScope(text, history);
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ reply }));
      return;
    }

    // ── /api/voice（语音对话）──
    if (pathname === '/api/voice' && req.method === 'POST') {
      const rawBody = await readBody(req, MAX_AUDIO_BODY);
      const contentType = req.headers['content-type'] || '';

      let userText;
      if (contentType.includes('application/json')) {
        const { text, history = [] } = JSON.parse(rawBody.toString('utf-8'));
        userText = text;
      } else {
        userText = await transcribeWithWhisper(rawBody);
      }

      console.log(`[voice] user: ${userText}`);
      const reply = await callDashScope(userText);
      console.log(`[voice] ops: ${reply}`);
      const mp3Buffer = await callMiniMaxTTS(reply);

      // X-Reply-Text 安全编码：确保客户端能正确解码
      let encodedReply;
      try {
        encodedReply = encodeURIComponent(reply);
      } catch (e) {
        encodedReply = encodeURIComponent('[编码失败]');
      }

      res.writeHead(200, {
        'Content-Type': 'audio/mpeg',
        'Content-Length': mp3Buffer.byteLength,
        'X-Reply-Text': encodedReply,
      });
      Readable.from(Buffer.from(mp3Buffer)).pipe(res);
      return;
    }

    // ── /api/tts（独立 TTS）──
    if (pathname === '/api/tts' && req.method === 'POST') {
      const rawBody = await readBody(req, MAX_JSON_BODY);
      const { text } = JSON.parse(rawBody.toString('utf-8'));
      if (!text) {
        res.writeHead(400, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ error: 'text is required' }));
        return;
      }
      const mp3Buffer = await callMiniMaxTTS(text);
      res.writeHead(200, {
        'Content-Type': 'audio/mpeg',
        'Content-Length': mp3Buffer.byteLength,
      });
      Readable.from(Buffer.from(mp3Buffer)).pipe(res);
      return;
    }

    // ── /api/status（健康检查）──
    if (pathname === '/api/status' && req.method === 'GET') {
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({
        status: 'ok',
        version: '1.1.0',
        security: {
          maxJsonBody: `${MAX_JSON_BODY / 1024}KB`,
          maxAudioBody: `${MAX_AUDIO_BODY / 1024 / 1024}MB`,
          requestTimeout: `${REQUEST_TIMEOUT / 1000}s`,
          corsMode: ALLOWED_ORIGINS.length > 0 ? 'whitelist' : 'open',
        },
        config: {
          hasDashScope: !!CONFIG.DASHSCOPE_API_KEY,
          hasMiniMax:   !!CONFIG.MINIMAX_API_KEY,
          hasWhisper:   !!CONFIG.OPENAI_API_KEY,
        }
      }));
      return;
    }

    // ── 静态文件 ──
    if (req.method === 'GET') {
      let filePath = path.join(__dirname, '../public', pathname);
      // 防止路径穿越攻击
      const publicDir = path.resolve(path.join(__dirname, '../public'));
      if (!path.resolve(filePath).startsWith(publicDir)) {
        res.writeHead(403);
        res.end('Forbidden');
        return;
      }
      if (!fs.existsSync(filePath)) {
        filePath = path.join(__dirname, '../public', 'index.html');
      }
      const ext = path.extname(filePath);
      res.writeHead(200, { 'Content-Type': MIME_TYPES[ext] || 'text/plain' });
      fs.createReadStream(filePath).pipe(res);
      return;
    }

    res.writeHead(404, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ error: 'Not Found' }));

  } catch (e) {
    console.error('[server error]', e.message);
    const statusCode = e.statusCode || 500;
    if (!res.headersSent) {
      res.writeHead(statusCode, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ error: e.message }));
    }
  }
});

// ── 启动 ─────────────────────────────────────────────────

validateEnv();

server.listen(PORT, () => {
  console.log(`
  Frank Voice Agent - Phase 1 MVP (Hardened)
  Server running at http://localhost:${PORT}

  Security Config:
    JSON  body limit : ${MAX_JSON_BODY / 1024} KB
    Audio body limit : ${MAX_AUDIO_BODY / 1024 / 1024} MB
    Request timeout  : ${REQUEST_TIMEOUT / 1000}s
    CORS mode        : ${ALLOWED_ORIGINS.length > 0 ? 'whitelist' : 'open (dev)'}

  API Keys:
    DashScope : ${CONFIG.DASHSCOPE_API_KEY ? 'OK' : 'MISSING'}
    MiniMax   : ${CONFIG.MINIMAX_API_KEY ? 'OK' : 'MISSING'}
    Whisper   : ${CONFIG.OPENAI_API_KEY ? 'OK' : 'optional, not set'}
  `);
});