declare module "cloudflare:workers" {
  export class DurableObject<Env = unknown> {
    constructor(ctx: import("./lib/cloudflare").DurableObjectState, env: Env);
  }
}

declare class WebSocketPair {
  0: WebSocket;
  1: WebSocket;
  constructor();
}

declare class WebSocketRequestResponsePair {
  constructor(request: string, response: string);
}
