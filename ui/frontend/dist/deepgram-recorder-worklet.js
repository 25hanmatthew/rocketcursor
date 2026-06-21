/* AudioWorklet that captures mono microphone audio and forwards raw Float32
   frames to the main thread, which converts them to linear16 (Int16) PCM for the
   Deepgram Voice Agent. Buffers to ~2048 samples (~128 ms at 16 kHz) to keep the
   postMessage/WebSocket send rate reasonable while staying low-latency. Running
   capture in the worklet (vs. a ScriptProcessorNode wired to destination) avoids
   the classic mic-to-speaker feedback loop. */
class DeepgramRecorderProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this._bufferSize = 2048;
    this._buffer = new Float32Array(this._bufferSize);
    this._offset = 0;
  }

  process(inputs) {
    const input = inputs[0];
    if (!input || input.length === 0) {
      return true;
    }
    const channel = input[0];
    if (!channel) {
      return true;
    }
    for (let i = 0; i < channel.length; i += 1) {
      this._buffer[this._offset] = channel[i];
      this._offset += 1;
      if (this._offset === this._bufferSize) {
        this.port.postMessage(this._buffer);
        this._buffer = new Float32Array(this._bufferSize);
        this._offset = 0;
      }
    }
    return true;
  }
}

registerProcessor("deepgram-recorder", DeepgramRecorderProcessor);
