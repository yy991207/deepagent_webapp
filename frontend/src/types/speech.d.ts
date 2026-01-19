export {};

declare global {
  type SpeechRecognitionAlternative = {
    transcript: string;
    confidence: number;
  };

  type SpeechRecognitionResult = {
    readonly length: number;
    item(index: number): SpeechRecognitionAlternative;
    [index: number]: SpeechRecognitionAlternative;
  };

  type SpeechRecognitionResultList = {
    readonly length: number;
    item(index: number): SpeechRecognitionResult;
    [index: number]: SpeechRecognitionResult;
  };

  type SpeechRecognitionEvent = Event & {
    readonly results: SpeechRecognitionResultList;
  };

  type SpeechRecognition = {
    lang: string;
    interimResults: boolean;
    continuous: boolean;
    start: () => void;
    stop: () => void;
    addEventListener: (
      type: "result" | "end",
      listener: (event: SpeechRecognitionEvent) => void
    ) => void;
  };

  interface Window {
    SpeechRecognition?: { new (): SpeechRecognition };
    webkitSpeechRecognition?: { new (): SpeechRecognition };
  }
}
