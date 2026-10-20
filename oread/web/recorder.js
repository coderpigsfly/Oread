// Runs in the browser's audio thread: hands each block of microphone samples to the page.
// ECMAScript 2020, like the rest of Oread's pages.
class Recorder extends AudioWorkletProcessor {
  process(inputs) {
    const channel = inputs[0] && inputs[0][0];
    if (channel) this.port.postMessage(channel.slice(0));
    return true;
  }
}

registerProcessor("oread-recorder", Recorder);
