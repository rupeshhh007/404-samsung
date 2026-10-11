import { describe, expect, it, vi } from 'vitest';
import { HttpProtocolError, InterlockHttpClient } from './http';

describe('browser voice session client', () => {
  it('requests a backend-owned session without client room or grant choices', async () => {
    const fetch = vi.fn(async () => new Response(JSON.stringify({
      session_id: 'server-session', room_name: 'server-room',
      livekit_url: 'wss://livekit.example', participant_token: 'short-token',
      ws_url: 'wss://backend.example/api/v1/sessions/server-session/stream',
    }), { status: 201, headers: { 'content-type': 'application/json' } }));
    const client = new InterlockHttpClient({ baseUrl: 'https://backend.example/api/v1', fetch });
    const result = await client.createVoiceSession();
    expect(result.session_id).toBe('server-session');
    expect(fetch).toHaveBeenCalledWith(
      'https://backend.example/api/v1/voice/sessions',
      expect.objectContaining({ method: 'POST', body: '{}' }),
    );
  });

  it('rejects an unexpected token response shape', async () => {
    const client = new InterlockHttpClient({ fetch: async () => new Response(JSON.stringify({
      session_id: 's', room_name: 'r', livekit_url: 'wss://example',
      participant_token: 'token', ws_url: '/stream', api_secret: 'must-not-be-here',
    }), { status: 201, headers: { 'content-type': 'application/json' } }) });
    await expect(client.createVoiceSession()).rejects.toBeInstanceOf(HttpProtocolError);
  });
});
