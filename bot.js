
require('dotenv').config();
const TelegramBot = require('node-telegram-bot-api');

const token = process.env.TELEGRAM_BOT_TOKEN;
const openRouterKey = process.env.OPENROUTER_API_KEY;
const channelId = process.env.CHANNEL_ID;

if (!token || !openRouterKey) {
  console.error('❌ Missing TELEGRAM_BOT_TOKEN or OPENROUTER_API_KEY in env');
  process.exit(1);
}

const bot = new TelegramBot(token, { polling: true });

async function askOpenRouter(userText) {
  const res = await fetch('https://openrouter.ai/api/v1/chat/completions', {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${openRouterKey}`,
      'HTTP-Referer': process.env.SITE_URL || 'https://t.me/',
      'X-Title': process.env.SITE_NAME || 'Telegram Bot',
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      model: process.env.MODEL || 'openai/gpt-4o',
      messages: [
        { role: 'system', content: 'You are a helpful, accurate, and concise assistant.' },
        { role: 'user', content: userText },
      ],
      temperature: 0.7,
    }),
  });

  if (!res.ok) {
    const errText = await res.text();
    throw new Error(`OpenRouter error ${res.status}: ${errText}`);
  }

  const data = await res.json();
  return data.choices?.[0]?.message?.content?.trim() || 'No response received.';
}

bot.on('message', async (msg) => {
  const chatId = msg.chat.id;
  const text = msg.text;

  if (!text || text.startsWith('/start')) {
    return bot.sendMessage(chatId, 'Hi! Ask me anything. 🤖');
  }

  try {
    await bot.sendChatAction(chatId, 'typing');
    const answer = await askOpenRouter(text);
    await bot.sendMessage(chatId, answer);

    if (channelId) {
      const channelText = `📩 New question:\n${text}\n\n🤖 Answer:\n${answer}`;
      await bot.sendMessage(channelId, channelText).catch((e) => {
        console.error('⚠️ Error sending to channel:', e.message);
      });
    }
  } catch (err) {
    console.error('❌ Error:', err);
    await bot.sendMessage(chatId, 'AI connection error. Please try again later.');
  }
});

console.log('✅ Bot is running...');
