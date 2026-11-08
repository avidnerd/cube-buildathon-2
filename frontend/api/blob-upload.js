// Issues short-lived tokens so the browser can upload a shared song straight to
// Vercel Blob (songs are larger than a function's 4.5 MB request limit).
import { handleUpload } from '@vercel/blob/client';

const ALLOWED_PATH = /^shares\/[a-f0-9]{16}\/[a-z0-9-]+\.(wav|json)$/;
const MAX_BYTES = 120 * 1024 * 1024;

export default async function handler(req, res) {
  if (req.method !== 'POST') return res.status(405).json({ error: 'POST only' });
  try {
    const result = await handleUpload({
      body: req.body,
      request: req,
      onBeforeGenerateToken: async pathname => {
        if (!ALLOWED_PATH.test(pathname)) throw new Error('Invalid upload path');
        return {
          allowedContentTypes: pathname.endsWith('.wav') ? ['audio/wav'] : ['application/json'],
          maximumSizeInBytes: MAX_BYTES,
          addRandomSuffix: false,
        };
      },
      onUploadCompleted: async () => {},
    });
    return res.status(200).json(result);
  } catch (error) {
    return res.status(400).json({ error: error.message });
  }
}
