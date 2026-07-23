import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useAnalysisStore } from '@/stores/analysis'

// Mock the API module
vi.mock('@/api/events', () => ({
  getTimelineData: vi.fn(),
  getEventDetail: vi.fn(),
  getRelatedEvents: vi.fn(),
  getProcessTree: vi.fn(),
  getDispositions: vi.fn(),
  addDisposition: vi.fn(),
  getEventContext: vi.fn(),
  getEventHostStats: vi.fn(),
  getEventImpact: vi.fn(),
  getEvents: vi.fn(),
  getEventStats: vi.fn(),
  getEventFilters: vi.fn(),
  updateEventStatus: vi.fn(),
  batchUpdateStatus: vi.fn(),
  assignEvent: vi.fn(),
  batchAssign: vi.fn(),
  getEventHistory: vi.fn(),
  getEventDisplay: vi.fn(),
  triggerAiNoiseReduce: vi.fn(),
  triggerEventVerdict: vi.fn(),
}))

import * as api from '@/api/events'

describe('AnalysisStore', () => {
  let store

  beforeEach(() => {
    setActivePinia(createPinia())
    store = useAnalysisStore()

    // Reset all mocks
    vi.clearAllMocks()

    // Setup default mock responses
    api.getTimelineData.mockResolvedValue({ data: { chains: [], events: [] } })
    api.getRelatedEvents.mockResolvedValue({ data: { items: [] } })
    api.getProcessTree.mockResolvedValue({ code: 0, data: { tree: [], current_pid: null } })
    api.getDispositions.mockResolvedValue({ data: { items: [] } })
    api.addDisposition.mockResolvedValue({ code: 0 })
    api.getEventContext.mockResolvedValue({ data: [] })
    api.getEventHostStats.mockResolvedValue({ data: null })
    api.getEventImpact.mockResolvedValue({ data: null })
    api.getEvents.mockResolvedValue({ data: { items: [], total: 0 } })
    api.getEventDetail.mockResolvedValue({ data: null })
  })

  // ── timelineByStage getter ──
  describe('timelineByStage getter', () => {
    it('returns empty array when timelineEvents is empty', () => {
      expect(store.timelineByStage).toEqual([])
    })

    it('groups events by attack_stage', () => {
      store.timelineEvents = [
        { id: 'e1', attack_stage: 'execution', event_type: 'process_start' },
        { id: 'e2', attack_stage: 'persistence', event_type: 'registry_modify' },
        { id: 'e3', attack_stage: 'execution', event_type: 'process_terminate' },
      ]

      const result = store.timelineByStage
      expect(result.length).toBe(2)
      expect(result[0].stage).toBe('execution')
      expect(result[0].count).toBe(2)
      expect(result[1].stage).toBe('persistence')
      expect(result[1].count).toBe(1)
    })

    it('marks current stage based on selectedEvent.attack_stage', () => {
      store.timelineEvents = [
        { id: 'e1', attack_stage: 'execution', event_type: 'process_start' },
        { id: 'e2', attack_stage: 'persistence', event_type: 'registry_modify' },
      ]
      store.selectedEvent = { id: 'e1', attack_stage: 'execution' }

      const result = store.timelineByStage
      expect(result[0].isCurrent).toBe(true)
      expect(result[1].isCurrent).toBe(false)
    })

    it('does not set isCurrent when selectedEvent has no attack_stage', () => {
      store.timelineEvents = [
        { id: 'e1', attack_stage: 'execution', event_type: 'process_start' },
      ]
      store.selectedEvent = { id: 'e1' }

      const result = store.timelineByStage
      expect(result[0].isCurrent).toBe(false)
    })

    it('maintains MITRE ATT&CK stage order', () => {
      // Events in reverse order
      store.timelineEvents = [
        { id: 'e1', attack_stage: 'impact', event_type: 'process_start' },
        { id: 'e2', attack_stage: 'initial_access', event_type: 'process_start' },
        { id: 'e3', attack_stage: 'execution', event_type: 'process_start' },
      ]

      const result = store.timelineByStage
      expect(result[0].stage).toBe('initial_access')
      expect(result[1].stage).toBe('execution')
      expect(result[result.length - 1].stage).toBe('impact')
    })

    it('includes unknown stage events at the end', () => {
      store.timelineEvents = [
        { id: 'e1', attack_stage: 'execution', event_type: 'process_start' },
        { id: 'e2', attack_stage: '', event_type: 'network_outbound' },
      ]

      const result = store.timelineByStage
      expect(result.length).toBe(2)
      expect(result[result.length - 1].stage).toBe('unknown')
      expect(result[result.length - 1].count).toBe(1)
    })

    it('assigns correct stage labels', () => {
      store.timelineEvents = [
        { id: 'e1', attack_stage: 'execution', event_type: 'process_start' },
      ]

      const result = store.timelineByStage
      expect(result[0].stageLabel).toBe('执行')
    })

    it('skips stages with zero events', () => {
      // Only add one stage - others should not appear
      store.timelineEvents = [
        { id: 'e1', attack_stage: 'execution', event_type: 'process_start' },
      ]

      const result = store.timelineByStage
      expect(result.length).toBe(1)
      expect(result[0].stage).toBe('execution')
    })
  })

  // ── currentStageEvents getter ──
  describe('currentStageEvents getter', () => {
    it('returns empty array when selectedEvent has no stage', () => {
      store.timelineEvents = [
        { id: 'e1', attack_stage: 'execution', event_type: 'process_start' },
      ]
      store.selectedEvent = null

      expect(store.currentStageEvents).toEqual([])
    })

    it('returns events matching current stage', () => {
      store.timelineEvents = [
        { id: 'e1', attack_stage: 'execution', event_type: 'process_start' },
        { id: 'e2', attack_stage: 'persistence', event_type: 'registry_modify' },
        { id: 'e3', attack_stage: 'execution', event_type: 'process_terminate' },
      ]
      store.selectedEvent = { id: 'e1', attack_stage: 'execution' }

      expect(store.currentStageEvents.length).toBe(2)
    })
  })

  // ── fetchProcessTree ──
  describe('fetchProcessTree', () => {
    it('sets processTree data on success', async () => {
      api.getProcessTree.mockResolvedValue({
        code: 0,
        data: {
          tree: [
            { pid: 1, name: 'init', depth: 0 },
            { pid: 2, name: 'explorer.exe', depth: 1 },
          ],
          current_pid: 2,
        },
      })

      await store.fetchProcessTree('evt-123')

      expect(store.processTree.length).toBe(2)
      expect(store.processTree[0].name).toBe('init')
      expect(store.currentProcessPid).toBe(2)
    })

    it('sets loading flag correctly', async () => {
      api.getProcessTree.mockImplementation(() => {
        return new Promise(resolve => {
          setTimeout(() => {
            resolve({ code: 0, data: { tree: [{ pid: 1, name: 'test' }], current_pid: null } })
          }, 10)
        })
      })

      const promise = store.fetchProcessTree('evt-123')
      expect(store.processTreeLoading).toBe(true)

      await promise
      expect(store.processTreeLoading).toBe(false)
    })

    it('handles API error gracefully', async () => {
      api.getProcessTree.mockRejectedValue(new Error('Network error'))

      await store.fetchProcessTree('evt-123')

      expect(store.processTree).toEqual([])
      expect(store.currentProcessPid).toBeNull()
      expect(store.processTreeLoading).toBe(false)
    })

    it('handles non-zero code response', async () => {
      api.getProcessTree.mockResolvedValue({
        code: -1,
        data: null,
      })

      await store.fetchProcessTree('evt-123')

      expect(store.processTree).toEqual([])
      expect(store.currentProcessPid).toBeNull()
    })

    it('does nothing when eventId is empty', async () => {
      await store.fetchProcessTree('')

      expect(api.getProcessTree).not.toHaveBeenCalled()
    })
  })

  // ── fetchRelatedEvents ──
  describe('fetchRelatedEvents', () => {
    it('sets relatedEvents from API response', async () => {
      api.getRelatedEvents.mockResolvedValue({
        data: { items: ['evt-1', 'evt-2', 'evt-3'] },
      })

      await store.fetchRelatedEvents('evt-123')

      expect(store.relatedEvents).toEqual(['evt-1', 'evt-2', 'evt-3'])
    })

    it('handles non-items response format', async () => {
      api.getRelatedEvents.mockResolvedValue({
        data: ['evt-a', 'evt-b'],
      })

      await store.fetchRelatedEvents('evt-123')

      expect(store.relatedEvents).toEqual(['evt-a', 'evt-b'])
    })

    it('handles API error gracefully', async () => {
      api.getRelatedEvents.mockRejectedValue(new Error('Network error'))

      await store.fetchRelatedEvents('evt-123')

      expect(store.relatedEvents).toEqual([])
    })

    it('does nothing when eventId is empty', async () => {
      await store.fetchRelatedEvents('')

      expect(api.getRelatedEvents).not.toHaveBeenCalled()
    })
  })

  // ── fetchTimeline ──
  describe('fetchTimeline', () => {
    it('sets timelineEvents from API response', async () => {
      api.getTimelineData.mockResolvedValue({
        data: {
          chains: [{ id: 'chain-1' }],
          events: [{ id: 'e1', attack_stage: 'execution' }],
        },
      })

      await store.fetchTimeline()

      expect(store.timelineData).toEqual([{ id: 'chain-1' }])
      expect(store.timelineEvents).toEqual([{ id: 'e1', attack_stage: 'execution' }])
    })

    it('handles API error gracefully', async () => {
      api.getTimelineData.mockRejectedValue(new Error('Network error'))

      await store.fetchTimeline()

      expect(store.timelineData).toEqual([])
      expect(store.timelineEvents).toEqual([])
    })
  })

  // ── fetchEventDetailEnhanced ──
  describe('fetchEventDetailEnhanced', () => {
    it('loads all enhanced data in parallel', async () => {
      api.getEventContext.mockResolvedValue({ data: [{ key: 'context' }] })
      api.getEventHostStats.mockResolvedValue({ data: { total_24h: 10 } })
      api.getEventImpact.mockResolvedValue({ data: { hosts: 5 } })
      api.getDispositions.mockResolvedValue({ data: { items: [{ id: 'd1' }] } })

      await store.fetchEventDetailEnhanced('evt-123')

      expect(store.eventContext).toEqual([{ key: 'context' }])
      expect(store.hostStats).toEqual({ total_24h: 10 })
      expect(store.impactScope).toEqual({ hosts: 5 })
      expect(store.dispositions).toEqual([{ id: 'd1' }])
    })

    it('handles partial failures gracefully', async () => {
      api.getEventContext.mockResolvedValue({ data: [{ key: 'context' }] })
      api.getEventHostStats.mockRejectedValue(new Error('Network error'))
      api.getEventImpact.mockResolvedValue({ data: { hosts: 5 } })
      api.getDispositions.mockRejectedValue(new Error('Network error'))

      await store.fetchEventDetailEnhanced('evt-123')

      expect(store.eventContext).toEqual([{ key: 'context' }])
      expect(store.hostStats).toBeNull()
      expect(store.impactScope).toEqual({ hosts: 5 })
      expect(store.dispositions).toEqual([])
    })
  })

  // ── addDispositionForEvent ──
  describe('addDispositionForEvent', () => {
    it('adds disposition and refreshes list on success', async () => {
      api.addDisposition.mockResolvedValue({ code: 0 })
      api.getDispositions.mockResolvedValue({ data: { items: [{ id: 'd1', comment: 'test', operator: 'user' }] } })

      await store.addDispositionForEvent('evt-123', { action: 'review', comment: 'test', operator: 'user' })

      expect(api.addDisposition).toHaveBeenCalledWith('evt-123', { action: 'review', comment: 'test', operator: 'user' })
      expect(store.dispositions).toEqual([{ id: 'd1', comment: 'test', operator: 'user' }])
    })
  })

  // ── P1 Data Actions ──
  describe('P1 data actions', () => {
    it('fetchProcessTree and fetchRelatedEvents can be called independently', async () => {
      api.getProcessTree.mockResolvedValue({ code: 0, data: { tree: [{ pid: 1 }], current_pid: null } })
      api.getRelatedEvents.mockResolvedValue({ data: { items: ['evt-1'] } })

      await Promise.all([
        store.fetchProcessTree('evt-123'),
        store.fetchRelatedEvents('evt-123'),
      ])

      expect(store.processTree).toEqual([{ pid: 1 }])
      expect(store.relatedEvents).toEqual(['evt-1'])
    })
  })
})
