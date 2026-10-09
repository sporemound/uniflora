import { useSyncExternalStore } from "react";
import {
  audioController,
  type AudioControllerState,
} from "../lib/audio-controller";

export function useAudioState(): AudioControllerState {
  return useSyncExternalStore(
    audioController.subscribe,
    audioController.getSnapshot,
    audioController.getServerSnapshot,
  );
}

