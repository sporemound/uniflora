import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";

export const LIMITS = { title: 120, observation: 2000 };

function validateSelection(selection, bounds) {
  assert.equal(Number.isFinite(selection.startSeconds), true, "finite start");
  assert.equal(Number.isFinite(selection.endSeconds), true, "finite end");
  assert.ok(selection.startSeconds < selection.endSeconds, "ordered range");
  assert.ok(selection.startSeconds >= bounds[0], "range lower bound");
  assert.ok(selection.endSeconds <= bounds[1], "range upper bound");
}

export class RoomModel {
  constructor({ roomId, artifactId, visualizationId, bounds = [0, 10] }) {
    this.roomId = roomId;
    this.artifactId = artifactId;
    this.visualizationId = visualizationId;
    this.bounds = bounds;
    this.revision = 0;
    this.presenter = null;
    this.findings = new Map();
    this.operations = new Map();
  }

  mutate(participant, operation) {
    if (this.operations.has(operation.operationId)) {
      return this.operations.get(operation.operationId);
    }
    assert.equal(operation.expectedRevision, this.revision, "expected room revision");
    let result;
    if (operation.type === "presenter:claim") {
      assert.ok(this.presenter === null || this.presenter === participant.id, "presenter conflict");
      this.presenter = participant.id;
      this.revision += 1;
      result = { type: "accepted", revision: this.revision };
    } else if (operation.type === "finding:create") {
      validateSelection(operation.selection, this.bounds);
      assert.ok(operation.title.trim() || operation.observation.trim(), "finding text");
      assert.ok(operation.title.length <= LIMITS.title, "title limit");
      assert.ok(operation.observation.length <= LIMITS.observation, "observation limit");
      this.revision += 1;
      const finding = {
        id: `finding_${randomUUID()}`,
        roomId: this.roomId,
        artifactId: this.artifactId,
        visualizationId: this.visualizationId,
        owner: participant.id,
        title: operation.title.trim(),
        observation: operation.observation.trim(),
        selection: operation.selection,
        revision: this.revision,
      };
      this.findings.set(finding.id, finding);
      result = { type: "created", revision: this.revision, finding };
    } else if (operation.type === "finding:update") {
      const finding = this.findings.get(operation.findingId);
      assert.ok(finding, "finding exists");
      assert.ok(finding.owner === participant.id || this.presenter === participant.id, "edit authorization");
      this.revision += 1;
      Object.assign(finding, {
        title: operation.title,
        observation: operation.observation,
        revision: this.revision,
      });
      result = { type: "updated", revision: this.revision, finding: { ...finding } };
    } else if (operation.type === "finding:delete") {
      const finding = this.findings.get(operation.findingId);
      assert.ok(finding, "finding exists");
      assert.ok(finding.owner === participant.id || this.presenter === participant.id, "delete authorization");
      this.findings.delete(operation.findingId);
      this.revision += 1;
      result = { type: "deleted", revision: this.revision, findingId: operation.findingId };
    } else {
      throw new Error(`Unsupported operation ${operation.type}`);
    }
    this.operations.set(operation.operationId, result);
    return result;
  }

  reconnectSnapshot() {
    return {
      roomId: this.roomId,
      revision: this.revision,
      findings: [...this.findings.values()].map((finding) => ({ ...finding })),
    };
  }
}
