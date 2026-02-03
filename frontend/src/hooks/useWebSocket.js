import { useEffect, useRef, useState, useCallback } from 'react'

export function useWebSocket(url, options = {}) {
  const { onMessage, onError, onOpen, onClose } = options
  const wsRef = useRef(null)
  const [isConnected, setIsConnected] = useState(false)
  const reconnectTimeoutRef = useRef(null)
  const shouldReconnectRef = useRef(true)
  const currentUrlRef = useRef(url)
  const connectionIdRef = useRef(0)  // Track connection attempts to prevent stale callbacks

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

  // Keep URL ref updated
  useEffect(() => {
    currentUrlRef.current = url
  }, [url])

  const connect = useCallback(() => {
    const targetUrl = currentUrlRef.current
    if (!targetUrl) return

    // Clear any pending reconnect
    clearTimeout(reconnectTimeoutRef.current)
    reconnectTimeoutRef.current = null

    // Increment connection ID to invalidate any stale callbacks
    const thisConnectionId = ++connectionIdRef.current

    // Close existing connection if any
    if (wsRef.current) {
      shouldReconnectRef.current = false
      wsRef.current.onclose = null  // Remove handler to prevent reconnect from old connection
      wsRef.current.close()
      wsRef.current = null
    }

    shouldReconnectRef.current = true

    try {
      const ws = new WebSocket(targetUrl)
      wsRef.current = ws

      ws.onopen = () => {
        // Check if this connection is still valid
        if (connectionIdRef.current !== thisConnectionId) {
          ws.close()
          return
        }
        setIsConnected(true)
        // Request state sync on connect/reconnect
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: 'get_state' }))
        }
        onOpenRef.current?.()
      }

      ws.onclose = () => {
        // Check if this connection is still valid
        if (connectionIdRef.current !== thisConnectionId) {
          return  // Stale connection, ignore
        }
        setIsConnected(false)
        onCloseRef.current?.()

        // Only reconnect if not intentionally closed and URL hasn't changed
        if (shouldReconnectRef.current && currentUrlRef.current === targetUrl) {
          reconnectTimeoutRef.current = setTimeout(() => {
            // Double-check URL hasn't changed during the timeout
            if (currentUrlRef.current === targetUrl) {
              connect()
            }
          }, 3000)
        }
      }

      ws.onerror = (error) => {
        if (connectionIdRef.current === thisConnectionId) {
          onErrorRef.current?.(error)
        }
      }

      ws.onmessage = (event) => {
        if (connectionIdRef.current !== thisConnectionId) {
          return  // Stale connection, ignore
        }
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
  }, [])  // No dependencies - uses refs for current values

  // Effect to handle URL changes and initial connection
  useEffect(() => {
    // Connect when URL changes
    connect()

    return () => {
      shouldReconnectRef.current = false
      clearTimeout(reconnectTimeoutRef.current)
      reconnectTimeoutRef.current = null
      if (wsRef.current) {
        wsRef.current.onclose = null  // Prevent reconnect on cleanup
        wsRef.current.close()
        wsRef.current = null
      }
    }
  }, [url, connect])

  const sendMessage = useCallback((data) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(data))
    }
  }, [])

  return { isConnected, sendMessage }
}
