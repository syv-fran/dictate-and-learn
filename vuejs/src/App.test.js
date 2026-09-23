import { render, screen, fireEvent } from '@testing-library/vue';
import { describe, it, expect } from "vitest";
import '@testing-library/jest-dom/vitest'; // toBeVisible etc. lots of handy fns
import { nextTick } from 'vue';
import { setTimeout } from 'timers/promises';
import App from "./App.vue";
import { vi } from 'vitest';
import eslintConfig from '../eslint.config.js';

// say that window.isSecureContext is true so recorder  doesn't exit early
vi.stubGlobal('isSecureContext', true);

// 2. create fake  MediaStream etc so that record can work...
class FakeMediaStream {
    constructor() { this.active = true; }
    getTracks() { return []; }
}
vi.stubGlobal('MediaStream', FakeMediaStream);

class FakeMediaRecorder {
    static isTypeSupported(mimeType) {
        return true;
    }
    constructor(stream, options) {
        this.stream = stream;
        this.options = options;
    }
    addEventListener(event, callback) {
    
    }
    start() { }
    resume() { }
    stop() { }
}
vi.stubGlobal('MediaRecorder', FakeMediaRecorder);


vi.stubGlobal('navigator', {
    ...global.navigator,
    mediaDevices: {
        getUserMedia: vi.fn().mockResolvedValue(new FakeMediaStream()),
    }
});

describe("Tabs.vue", () => {
    it("records audio", async () => {
 
        const { container } = render(App);

        const audioPlayer = container.querySelector('#RecAudioPlayer');
        // screen.debug(audioPlayer);
        expect(audioPlayer).not.toBeVisible();
        const buttons = await screen.findAllByRole("button");
        expect(buttons).toHaveLength(5);
        expect(buttons[2].hasAttribute('disabled')).toBeTruthy();
        expect(buttons[1].textContent).toContain('Record');
        await fireEvent.click(buttons[1]);
        await nextTick();  
        //screen.debug(buttons[2]);
        expect(buttons[2].hasAttribute('disabled')).toBeFalsy();
        expect(buttons[1].textContent).toContain("Pause");
        await fireEvent.click(buttons[2]);
        expect(buttons[2].hasAttribute('disabled')).toBeTruthy();
        expect(audioPlayer).toBeVisible();

    });
});