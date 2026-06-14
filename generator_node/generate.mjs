import { rakutenAI } from '@evex/rakutenai';
import { streamText } from 'ai';

// Suppress AI SDK v5 compatibility warnings
globalThis.AI_SDK_LOG_WARNINGS = false;

const prompt = process.argv[2];
if (!prompt) {
  process.stderr.write('Usage: node generate.mjs <prompt>\n');
  process.exit(1);
}

// Suppress unhandled rejection from rakutenai stream cleanup
process.on('unhandledRejection', () => {});

try {
  const result = await streamText({
    model: rakutenAI('normal'),
    prompt,
  });

  for await (const chunk of result.textStream) {
    process.stdout.write(chunk);
  }

  process.stdout.write('\n');
  // Give the cleanup a moment then exit cleanly before the stream-locked error fires
  await new Promise(r => setTimeout(r, 100));
  process.exit(0);
} catch (err) {
  process.stderr.write(`Error: ${err.message}\n`);
  process.exit(1);
}
