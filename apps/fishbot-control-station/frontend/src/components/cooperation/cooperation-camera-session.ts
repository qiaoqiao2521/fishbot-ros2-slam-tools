import { CooperationFrameBuffer } from '@/lib/cooperation-frame'
import { cooperationFrameSourceKey, type CooperationState } from '@/lib/cooperation'

type BufferOptions = ConstructorParameters<typeof CooperationFrameBuffer>[0]
type FrameBuffer = Pick<CooperationFrameBuffer, 'request' | 'dispose'>
export type CameraCallbacks = {
  scene: Pick<BufferOptions, 'display' | 'observe'>
  rear: Pick<BufferOptions, 'display' | 'observe'>
}

/** Visibility adapter only. Existing buffers own decoding, expiry and latest-frame queues. */
export class CooperationCameraSession {
  private callbacks: CameraCallbacks
  private create: (options: BufferOptions) => FrameBuffer
  private scene: FrameBuffer | null = null
  private rear: FrameBuffer | null = null
  private disposed = false

  constructor(callbacks: CameraCallbacks, create: (options: BufferOptions) => FrameBuffer = (options) => new CooperationFrameBuffer(options)) {
    this.callbacks = callbacks
    this.create = create
  }

  update(state: CooperationState | null, visible: boolean, rearVisible: boolean): void {
    if (this.disposed) return
    if (!visible) { this.release(); return }
    const source = cooperationFrameSourceKey(state)
    if (!rearVisible) {
      this.scene ??= this.create(this.callbacks.scene)
      this.scene.request(source, state?.frame.available ? state.frame.stamp : null, state?.episode_id)
    } else {
      this.scene?.dispose()
      this.scene = null
    }
    if (rearVisible) {
      this.rear ??= this.create({ ...this.callbacks.rear, endpoint: 'vision-frame.jpg' })
      const vision = state?.vision_frame
      this.rear.request(source, vision?.available ? vision.stamp : null, state?.episode_id, vision)
    } else {
      this.rear?.dispose()
      this.rear = null
    }
  }

  private release(): void {
    this.scene?.dispose(); this.scene = null
    this.rear?.dispose(); this.rear = null
  }

  dispose(): void { this.disposed = true; this.release() }
}
