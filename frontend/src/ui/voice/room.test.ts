import { describe, expect, it, vi } from 'vitest';
import type { Room } from 'livekit-client';
import { RoomEvent, Track } from 'livekit-client';
import { connectVoiceRoom, setVoiceMuted, stopVoiceRoom, VOICE_AUDIO_CAPTURE_OPTIONS } from './room';

function fakeRoom(connect = vi.fn(async () => undefined)) {
  const listeners = new Map<string, (...args: any[]) => void>();
  const setMicrophoneEnabled = vi.fn(async (_enabled: boolean) => undefined);
  const room = {
    on: vi.fn((event: string, handler: (...args: any[]) => void) => { listeners.set(event, handler); }),
    connect, startAudio: vi.fn(async () => undefined),
    localParticipant: { identity: 'browser', setMicrophoneEnabled },
    remoteParticipants: new Map(),
  } as unknown as Room;
  return { room, listeners, setMicrophoneEnabled };
}

describe('browser voice connection', () => {
  it('connects with the backend token, plays agent audio, and publishes the microphone', async () => {
    const { room, listeners, setMicrophoneEnabled } = fakeRoom();
    const elements = new Set<HTMLMediaElement>();
    const appendAudio = vi.fn();
    const onAgentSpeaking = vi.fn();
    await connectVoiceRoom(room, 'wss://lk.example', 'browser-token', elements, {
      appendAudio, onAgentSpeaking, onDisconnected: vi.fn(), onWorkerDisconnected: vi.fn(),
    });
    expect(room.connect).toHaveBeenCalledWith('wss://lk.example', 'browser-token');
    expect(room.startAudio).toHaveBeenCalledOnce();
    expect(setMicrophoneEnabled).toHaveBeenCalledWith(true, VOICE_AUDIO_CAPTURE_OPTIONS);
    const element = { dataset: {}, remove: vi.fn() } as unknown as HTMLMediaElement;
    const detach = vi.fn(() => [element]);
    const audio = { kind: Track.Kind.Audio, attach: () => element, detach };
    listeners.get(RoomEvent.TrackSubscribed)?.(audio);
    expect(appendAudio).toHaveBeenCalledWith(element);
    expect(elements.has(element)).toBe(true);
    listeners.get(RoomEvent.ActiveSpeakersChanged)?.([{ identity: 'worker' }]);
    expect(onAgentSpeaking).toHaveBeenCalledWith(true);
    listeners.get(RoomEvent.TrackUnsubscribed)?.(audio);
    expect(detach).toHaveBeenCalledOnce();
    expect(elements.size).toBe(0);
  });

  it('does not claim listening if microphone permission is denied', async () => {
    const { room, setMicrophoneEnabled } = fakeRoom();
    setMicrophoneEnabled.mockRejectedValueOnce(Object.assign(new Error('denied'), { name: 'NotAllowedError' }));
    await expect(connectVoiceRoom(room, 'wss://lk.example', 'token', new Set(), {
      onAgentSpeaking: vi.fn(), onDisconnected: vi.fn(), onWorkerDisconnected: vi.fn(),
    })).rejects.toMatchObject({ name: 'NotAllowedError' });
  });

  it('reports worker and room disconnects through transport callbacks', async () => {
    const { room, listeners } = fakeRoom();
    const onWorkerDisconnected = vi.fn();
    const onDisconnected = vi.fn();
    await connectVoiceRoom(room, 'wss://lk.example', 'token', new Set(), {
      onAgentSpeaking: vi.fn(), onDisconnected, onWorkerDisconnected,
    });
    listeners.get(RoomEvent.ParticipantDisconnected)?.();
    listeners.get(RoomEvent.Disconnected)?.();
    expect(onWorkerDisconnected).toHaveBeenCalledOnce();
    expect(onDisconnected).toHaveBeenCalledOnce();
  });

  it('mutes and unmutes only the microphone track', async () => {
    const { room, setMicrophoneEnabled } = fakeRoom();
    await setVoiceMuted(room, true);
    await setVoiceMuted(room, false);
    expect(setMicrophoneEnabled.mock.calls).toEqual([[false, undefined], [true, VOICE_AUDIO_CAPTURE_OPTIONS]]);
  });
});

describe('browser voice cleanup', () => {
  it('detaches agent audio, unpublishes and stops microphone, and disconnects', async () => {
    const remove = vi.fn();
    const detach = vi.fn(() => [{ remove }]);
    const stop = vi.fn();
    const unpublishTrack = vi.fn(async () => undefined);
    const disconnect = vi.fn(async () => undefined);
    const removeAllListeners = vi.fn();
    const mic = { stop };
    const room = {
      remoteParticipants: new Map([['worker', {
        audioTrackPublications: new Map([['audio', { track: { detach } }]]),
      }]]),
      localParticipant: {
        audioTrackPublications: new Map([['mic', { track: mic }]]), unpublishTrack,
      },
      disconnect, removeAllListeners,
    } as unknown as Room;
    const element = { remove: vi.fn() } as unknown as HTMLMediaElement;
    const elements = new Set([element]);
    await stopVoiceRoom(room, elements);
    expect(detach).toHaveBeenCalledOnce();
    expect(remove).toHaveBeenCalledOnce();
    expect(unpublishTrack).toHaveBeenCalledWith(mic);
    expect(stop).toHaveBeenCalledOnce();
    expect(disconnect).toHaveBeenCalledWith(true);
    expect(removeAllListeners).toHaveBeenCalledOnce();
    expect(element.remove).toHaveBeenCalledOnce();
    expect(elements.size).toBe(0);
  });

  it('still disconnects and removes audio when unpublish fails', async () => {
    const stop = vi.fn();
    const disconnect = vi.fn(async () => undefined);
    const room = {
      remoteParticipants: new Map(), removeAllListeners: vi.fn(),
      localParticipant: {
        audioTrackPublications: new Map([['mic', { track: { stop } }]]),
        unpublishTrack: vi.fn(async () => { throw new Error('unpublish failed'); }),
      }, disconnect,
    } as unknown as Room;
    const element = { remove: vi.fn() } as unknown as HTMLMediaElement;
    const elements = new Set([element]);
    await expect(stopVoiceRoom(room, elements)).rejects.toThrow('unpublish failed');
    expect(stop).toHaveBeenCalledOnce();
    expect(disconnect).toHaveBeenCalledOnce();
    expect(element.remove).toHaveBeenCalledOnce();
  });
});
