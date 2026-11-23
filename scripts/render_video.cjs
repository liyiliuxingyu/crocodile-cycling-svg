#!/usr/bin/env node
'use strict';

// Rasterize the sampler's static SVGs with Sharp, then stream PNGs to FFmpeg.
// No browser, web request, screenshot timing or machine-specific path is used.
const fs = require('node:fs/promises');
const path = require('node:path');
const { spawn } = require('node:child_process');

const ROOT = path.resolve(__dirname, '..');

function parseArgs(argv) {
  const options = {
    frames: 'build/frames',
    output: 'build/crocodile-cycling.mp4',
    ffmpeg: process.env.FFMPEG_PATH || 'ffmpeg',
    crf: 18,
    preset: 'medium',
    limit: null,
  };
  for (let index = 0; index < argv.length; index += 1) {
    const argument = argv[index];
    if (argument === '--help' || argument === '-h') {
      console.log(`Usage: node scripts/render_video.cjs [options]

  --frames DIR     Directory containing manifest.json and static SVG frames
                   (default: build/frames)
  --output FILE    MP4 destination (default: build/crocodile-cycling.mp4)
  --ffmpeg FILE    FFmpeg executable (default: FFMPEG_PATH or ffmpeg on PATH)
  --crf NUMBER     H.264 quality, 0 through 51 (default: 18)
  --preset NAME    libx264 preset (default: medium)
  --limit NUMBER   Encode only the first N frames for a quick smoke test

Relative paths resolve from the repository root. Dependencies: npm install.
SHARP_MODULE_PATH may optionally point to an existing Sharp module for testing;
normal use loads require('sharp').`);
      process.exit(0);
    }
    const key = argument.slice(2);
    if (!argument.startsWith('--') || !Object.hasOwn(options, key)) {
      throw new Error(`Unknown argument: ${argument}`);
    }
    if (index + 1 >= argv.length) throw new Error(`Missing value for ${argument}`);
    options[key] = argv[++index];
  }
  options.crf = Number(options.crf);
  if (!Number.isInteger(options.crf) || options.crf < 0 || options.crf > 51) {
    throw new Error('--crf must be an integer between 0 and 51.');
  }
  if (options.limit !== null) {
    options.limit = Number(options.limit);
    if (!Number.isSafeInteger(options.limit) || options.limit < 1) {
      throw new Error('--limit must be a positive integer.');
    }
  }
  const presets = ['ultrafast', 'superfast', 'veryfast', 'faster', 'fast', 'medium',
    'slow', 'slower', 'veryslow', 'placebo'];
  if (!presets.includes(options.preset)) throw new Error('Unknown libx264 preset.');
  return options;
}

function repositoryPath(value) {
  return path.isAbsolute(value) ? value : path.resolve(ROOT, value);
}

function validateManifest(manifest) {
  if (manifest.format_version !== 1 || manifest.frame_pattern !== 'frame-%06d.svg') {
    throw new Error('Unsupported manifest. Run scripts/sample_frames.py first.');
  }
  for (const name of ['width', 'height', 'frame_count']) {
    if (!Number.isSafeInteger(manifest[name]) || manifest[name] < 1) {
      throw new Error(`Invalid manifest field: ${name}`);
    }
  }
  if (manifest.width % 2 || manifest.height % 2) {
    throw new Error('yuv420p requires even dimensions.');
  }
  if (!Number.isFinite(manifest.fps) || manifest.fps <= 0) {
    throw new Error('Invalid frame rate in manifest.');
  }
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  let sharp;
  try {
    sharp = require(process.env.SHARP_MODULE_PATH || 'sharp');
  } catch (error) {
    throw new Error(`Cannot load Sharp. Run npm install first. ${error.message}`);
  }
  const framesDir = repositoryPath(options.frames);
  const output = repositoryPath(options.output);
  if (path.extname(output).toLowerCase() !== '.mp4') {
    throw new Error('--output must have an .mp4 extension.');
  }
  const manifest = JSON.parse(await fs.readFile(path.join(framesDir, 'manifest.json'), 'utf8'));
  validateManifest(manifest);
  const count = options.limit === null ? manifest.frame_count : Math.min(options.limit, manifest.frame_count);
  await fs.mkdir(path.dirname(output), { recursive: true });
  const temporary = path.join(path.dirname(output), `.${path.basename(output, '.mp4')}-${process.pid}.tmp.mp4`);
  const args = ['-hide_banner', '-loglevel', 'error', '-nostdin', '-y',
    '-f', 'image2pipe', '-framerate', String(manifest.fps), '-vcodec', 'png', '-i', 'pipe:0',
    '-an', '-c:v', 'libx264', '-preset', options.preset, '-crf', String(options.crf),
    '-pix_fmt', 'yuv420p', '-movflags', '+faststart', '-frames:v', String(count), temporary];
  const encoder = spawn(options.ffmpeg, args, { stdio: ['pipe', 'ignore', 'pipe'] });
  let stderr = '';
  encoder.stderr.on('data', chunk => { stderr = (stderr + chunk.toString()).slice(-12000); });
  encoder.stdin.on('error', () => {}); // Individual writes report the same error below.
  const completion = new Promise(resolve => {
    encoder.once('error', error => resolve({ error }));
    encoder.once('close', (code, signal) => resolve({ code, signal }));
  });
  try {
    for (let index = 0; index < count; index += 1) {
      const input = path.join(framesDir, `frame-${String(index).padStart(6, '0')}.svg`);
      const png = await sharp(await fs.readFile(input), { density: 72 })
        .resize(manifest.width, manifest.height, { fit: 'fill' })
        .flatten({ background: '#f4f2e9' }).removeAlpha().png().toBuffer();
      await new Promise((resolve, reject) => {
        encoder.stdin.write(png, error => error ? reject(error) : resolve());
      });
      if ((index + 1) % 30 === 0 || index + 1 === count) {
        console.log(`Rendered ${index + 1}/${count} frames`);
      }
    }
    encoder.stdin.end();
    const result = await completion;
    if (result.error) throw result.error;
    if (result.code !== 0) {
      throw new Error(`FFmpeg exited with ${result.code ?? result.signal}: ${stderr.trim()}`);
    }
    await fs.rename(temporary, output);
    console.log(`Created ${output}`);
    console.log(`${manifest.width}x${manifest.height}, ${manifest.fps} fps, ` +
      `${count / manifest.fps} seconds, H.264/yuv420p, no audio.`);
  } catch (error) {
    encoder.stdin.destroy();
    encoder.kill('SIGTERM');
    const result = await completion;
    await fs.unlink(temporary).catch(() => {});
    const detail = result.error?.message || stderr.trim();
    throw new Error(`${error.message}${detail ? `\n${detail}` : ''}`);
  }
}

main().catch(error => {
  console.error(`Video export failed: ${error.message}`);
  process.exitCode = 1;
});
