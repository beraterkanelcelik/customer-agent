import { useEffect, useRef, useState, useCallback } from 'react'

export function useWebSocket(url, options = {}) {
  const { onMessage, onError, onOpen, onClose } = options
  const wsRef = useRef(null)
  const [isConnected, setIsConnected] = useState(false)
  const reconnectTimeoutRef = useRef(null)
  const shouldReconnectRef = useRef(true)

  // Use refs to store callbacks to avoid reconnecting on callback changes
  const onMessageRef = useRef(onMessage)
  const onErrorRef = useRef(onError)
  const onOpenRef = useRef(onOpen)
  const onCloseRef = useRef(onClose)

  // Keep refs updated
  useEffect(() => {
    onMessageRef.current = onMessage
    onErrorRef.current = onError
    onOpenRef.current = onOpen
    onCloseRef.current = onClose
  }, [onMessage, onError, onOpen, onClose])

  const connect = useCallback(() => {
    if (!url) return

    // Clear any pending reconnect
    clearTimeout(reconnectTimeoutRef.current)

    // Close existing connection if any
    if (wsRef.current) {
      shouldReconnectRef.current = false
      wsRef.current.close()
    }

    shouldReconnectRef.current = true

    try {
      wsRef.current = new WebSocket(url)

      wsRef.current.onopen = () => {
        setIsConnected(true)
        // Request state sync on connect/reconnect
        if (wsRef.current?.readyState === WebSocket.OPEN) {
          wsRef.current.send(JSON.stringify({ type: 'get_state' }))
        }
        onOpenRef.current?.()
      }

      wsRef.current.onclose = () => {
        setIsConnected(false)
        onCloseRef.current?.()

        // Only reconnect if not intentionally closed
        if (shouldReconnectRef.current && url) {
          reconnectTimeoutRef.current = setTimeout(() => {
            connect()
          }, 3000)
        }
      }

      wsRef.current.onerror = (error) => {
        onErrorRef.current?.(error)
      }

      wsRef.current.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data)
          onMessageRef.current?.(data)
        } catch (e) {
          console.error('Failed to parse WS message:', e)
        }
      }
    } catch (error) {
      onErrorRef.current?.(error)
    }
  }, [url])  // Only reconnect when URL changes

  useEffect(() => {
    connect()

    return () => {
      shouldReconnectRef.current = false
      clearTimeout(reconnectTimeoutRef.current)
      wsRef.current?.close()
    }
  }, [connect])

  const sendMessage = useCallback((data) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(data))
    }
  }, [])

  return { isConnected, sendMessage }
}
