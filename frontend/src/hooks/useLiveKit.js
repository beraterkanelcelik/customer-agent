import { useRef, useState, useCallback } from 'react'
import { Room, RoomEvent, Track } from 'livekit-client'

export function useLiveKit() {
  const roomRef = useRef(null)
  const [isConnected, setIsConnected] = useState(false)
  const [isMuted, setIsMuted] = useState(false)

  const connect = useCallback(async (url, token) => {
    try {
      const room = new Room()
      roomRef.current = room

      // Set up event handlers
      room.on(RoomEvent.Connected, () => {
        console.log('Connected to LiveKit room')
        setIsConnected(true)
      })

      room.on(RoomEvent.Disconnected, () => {
        console.log('Disconnected from LiveKit room')
        setIsConnected(false)
      })

      room.on(RoomEvent.TrackSubscribed, (track, publication, participant) => {
        if (track.kind === Track.Kind.Audio) {
          const audioElement = track.attach()
          document.body.appendChild(audioElement)
        }
      })

      // Connect
      await room.connect(url, token)

      // Enable microphone
      await room.localParticipant.setMicrophoneEnabled(true)

    } catch (error) {
      console.error('LiveKit connection error:', error)
      throw error
    }
  }, [])

  const disconnect = useCallback(async () => {
    if (roomRef.current) {
      await roomRef.current.disconnect()
      roomRef.current = null
    }
    setIsConnected(false)
  }, [])

  const toggleMute = useCallback(async () => {
    if (roomRef.current) {
      const newMuted = !isMuted
      await roomRef.current.localParticipant.setMicrophoneEnabled(!newMuted)
      setIsMuted(newMuted)
    }
  }, [isMuted])

  return {
    connect,
    disconnect,
    toggleMute,
    isConnected,
    isMuted
  }
}
