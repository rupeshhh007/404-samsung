import { RoomEvent, Track, type Room } from 'livekit-client';

export interface VoiceRoomCallbacks {
  readonly onAgentSpeaking: (speaking: boolean) => void;
  readonly onWorkerDisconnected: () => void;
  readonly onDisconnected: () => void;
  readonly appendAudio?: (element: HTMLMediaElement) => void;
}

export const VOICE_AUDIO_CAPTURE_OPTIONS = {
  echoCancellation: true,
  noiseSuppression: true,
  autoGainControl: true,
  channelCount: 1,
  sampleRate: 48_000,
  // Chromium can apply stronger single-speaker isolation when available.
  // Unsupported browsers ignore the experimental constraint.
  voiceIsolation: true,
} as const;

/** LiveKit has audio transport only; no business projection is read here. */
export async function connectVoiceRoom(
  room: Room, url: string, token: string, elements: Set<HTMLMediaElement>,
  callbacks: VoiceRoomCallbacks,
): Promise<void> {
  room.on(RoomEvent.TrackSubscribed, (track) => {
    if (track.kind !== Track.Kind.Audio) return;
    const element = track.attach();
    element.dataset.interlockVoiceAudio = 'true';
    (callbacks.appendAudio ?? ((audio) => document.body.appendChild(audio)))(element);
    elements.add(element);
  });
  room.on(RoomEvent.TrackUnsubscribed, (track) => {
    for (const element of track.detach()) {
      elements.delete(element);
      element.remove();
    }
  });
  room.on(RoomEvent.ActiveSpeakersChanged, (speakers) => {
    callbacks.onAgentSpeaking(speakers.some(
      (speaker) => speaker.identity !== room.localParticipant.identity,
    ));
  });
  room.on(RoomEvent.ParticipantDisconnected, () => {
    if (room.remoteParticipants.size === 0) callbacks.onWorkerDisconnected();
  });
  room.on(RoomEvent.Disconnected, callbacks.onDisconnected);
  await room.connect(url, token);
  await room.startAudio();
  await room.localParticipant.setMicrophoneEnabled(true, VOICE_AUDIO_CAPTURE_OPTIONS);
}

export async function setVoiceMuted(room: Room, muted: boolean): Promise<void> {
  await room.localParticipant.setMicrophoneEnabled(!muted, muted ? undefined : VOICE_AUDIO_CAPTURE_OPTIONS);
}

/** Release every browser audio resource, even if disconnect itself fails. */
export async function stopVoiceRoom(room: Room | null, elements: Set<HTMLMediaElement>): Promise<void> {
  let failure: unknown;
  if (room) {
    room.removeAllListeners();
    for (const participant of room.remoteParticipants.values()) {
      for (const publication of participant.audioTrackPublications.values()) {
        try {
          publication.track?.detach().forEach((element) => element.remove());
        } catch (error) {
          failure ??= error;
        }
      }
    }
    for (const publication of room.localParticipant.audioTrackPublications.values()) {
      if (!publication.track) continue;
      try {
        await room.localParticipant.unpublishTrack(publication.track);
      } catch (error) {
        failure ??= error;
      } finally {
        publication.track.stop();
      }
    }
    try {
      await room.disconnect(true);
    } catch (error) {
      failure ??= error;
    }
  }
  for (const element of elements) element.remove();
  elements.clear();
  if (failure) throw failure;
}
