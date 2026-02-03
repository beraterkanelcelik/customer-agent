import React, { useEffect, useRef } from 'react'
import { Link } from 'react-router-dom'
import { ArrowLeft, GitBranch } from 'lucide-react'
import mermaid from 'mermaid'

// Initialize mermaid with dark theme
mermaid.initialize({
  startOnLoad: false,
  theme: 'dark',
  themeVariables: {
    primaryColor: '#6366f1',
    primaryTextColor: '#fff',
    primaryBorderColor: '#4f46e5',
    lineColor: '#94a3b8',
    secondaryColor: '#1e1b4b',
    tertiaryColor: '#312e81',
    background: '#0f172a',
    mainBkg: '#1e293b',
    nodeBorder: '#4f46e5',
    clusterBkg: '#1e293b',
    clusterBorder: '#334155',
    titleColor: '#f1f5f9',
    edgeLabelBackground: '#1e293b'
  },
  flowchart: {
    curve: 'basis',
    padding: 20
  }
})

const mainFlowChart = `
flowchart TB
    subgraph Twilio["Twilio Voice Pipeline"]
        PHONE[Customer Phone] --> TWILIO[Twilio]
        TWILIO --> WEBHOOK["/api/voice/incoming"]
        WEBHOOK --> STREAM["Media Stream WebSocket"]
        STREAM --> VAD[VAD Detection]
        VAD --> STT[Faster-Whisper STT]
        STT --> TEXT[Transcribed Text]
        AUDIO[TTS Audio] --> MULAW[Convert to mulaw]
        MULAW --> STREAM
    end

    subgraph Backend["FastAPI Backend"]
        TEXT --> SERVICE[conversation_service]
        SERVICE --> GRAPH[LangGraph Workflow]
        GRAPH --> RESPONSE[Response Text]
        RESPONSE --> TTS[Kokoro TTS]
        TTS --> AUDIO
    end

    subgraph LangGraph["LangGraph Workflow - Tool Calling Loop"]
        direction TB
        START((Start)) --> PRE[preprocess_node]
        PRE --> AGENT[agent_node]
        AGENT --> COND{has tool_calls?}
        COND -->|Yes| TOOLS[tool_node]
        TOOLS --> AGENT
        COND -->|No| POST[postprocess_node]
        POST --> DONE((End))
    end

    subgraph Capabilities["Agent Capabilities via Tools"]
        direction LR
        FAQ[FAQ Search]
        BOOK[Booking]
        CUST[Customer Lookup]
        ESC[Escalation]
        CALL[Call Control]
    end

    GRAPH --> LangGraph
    TOOLS --> Capabilities

    style Twilio fill:#1e3a5f,stroke:#3b82f6
    style Backend fill:#1e293b,stroke:#6366f1
    style LangGraph fill:#312e81,stroke:#8b5cf6
    style Capabilities fill:#1e3a3f,stroke:#14b8a6
`

const toolFlowChart = `
flowchart LR
    subgraph Tools["Available Tools - 15 Total"]
        direction TB

        subgraph FAQ_Tools["FAQ Tools"]
            search_faq[search_faq]
            list_services[list_services]
        end

        subgraph Booking_Tools["Booking Tools"]
            check_availability[check_availability]
            book_appointment[book_appointment]
            reschedule[reschedule_appointment]
            cancel[cancel_appointment]
            list_inventory[list_inventory]
            get_appointments[get_customer_appointments]
        end

        subgraph Customer_Tools["Customer Tools"]
            get_customer[get_customer]
            create_customer[create_customer]
        end

        subgraph Slot_Tools["Slot Management"]
            update_booking_info[update_booking_info]
            set_customer_id[set_customer_identified]
            get_date[get_todays_date]
        end

        subgraph Call_Tools["Call & Escalation"]
            end_call[end_call]
            request_human[request_human_agent]
        end
    end

    style FAQ_Tools fill:#1e3a5f,stroke:#3b82f6
    style Booking_Tools fill:#1e3a3f,stroke:#14b8a6
    style Customer_Tools fill:#3a1e3f,stroke:#d946ef
    style Slot_Tools fill:#3a3a1e,stroke:#eab308
    style Call_Tools fill:#3a1e1e,stroke:#ef4444
`

const bookingFlowChart = `
flowchart TB
    START((User: Book)) --> MODEL1[Call Model]

    MODEL1 --> TC1{tool_calls?}
    TC1 -->|No| ASK_NAME[Ask Name]
    ASK_NAME --> USER1((User: John))

    USER1 --> MODEL2[Call Model]
    MODEL2 --> TC2{tool_calls?}
    TC2 -->|No| ASK_PHONE[Ask Phone]
    ASK_PHONE --> USER2((User: 555-1234))

    USER2 --> MODEL3[Call Model]
    MODEL3 --> TC3{tool_calls?}
    TC3 -->|No| ASK_EMAIL[Ask Email]
    ASK_EMAIL --> USER3((User: john@email))

    USER3 --> MODEL4[Call Model]
    MODEL4 --> TC4{tool_calls?}
    TC4 -->|Yes| CREATE[Tool: create_customer]
    CREATE --> MODEL4B[Call Model]
    MODEL4B --> ASK_TYPE[Ask Type]
    ASK_TYPE --> USER4((User: Test drive))

    USER4 --> MODEL5[Call Model]
    MODEL5 --> TC5{tool_calls?}
    TC5 -->|Yes| LIST[Tool: list_inventory]
    LIST --> MODEL5B[Call Model]
    MODEL5B --> SHOW_CARS[Show Cars, Ask Which]
    SHOW_CARS --> USER5((User: Civic))

    USER5 --> MODEL6[Call Model]
    MODEL6 --> ASK_DATE[Ask Date/Time]
    ASK_DATE --> USER6((User: Tomorrow 10am))

    USER6 --> MODEL7[Call Model]
    MODEL7 --> TC7{tool_calls?}
    TC7 -->|Yes| CHECK[Tool: check_availability]
    CHECK --> MODEL7B[Call Model]
    MODEL7B --> CONFIRM[Confirm Details]
    CONFIRM --> USER7((User: Yes))

    USER7 --> MODEL8[Call Model]
    MODEL8 --> TC8{tool_calls?}
    TC8 -->|Yes| BOOK[Tool: book_appointment]
    BOOK --> MODEL8B[Call Model]
    MODEL8B --> SUCCESS((Booking Complete!))

    style START fill:#6366f1,stroke:#4f46e5
    style SUCCESS fill:#22c55e,stroke:#16a34a
    style CREATE fill:#d946ef,stroke:#c026d3
    style BOOK fill:#14b8a6,stroke:#0d9488
    style CHECK fill:#eab308,stroke:#ca8a04
    style LIST fill:#3b82f6,stroke:#2563eb
`

const graphNodesChart = `
flowchart TB
    subgraph Graph["LangGraph State Machine - graph.py"]
        direction TB

        subgraph PreNode["preprocess_node"]
            PRE_DESC["• Check notifications_queue<br/>• Deliver escalation results<br/>• Set prepend_message<br/>• Update human_agent_status"]
        end

        subgraph AgentNode["agent_node"]
            AGENT_DESC["• Build context from state<br/>• Inject system prompt<br/>• Call LLM with bound tools<br/>• Return AI message"]
        end

        subgraph ToolNode["tool_node"]
            TOOL_DESC["• Extract tool_calls from AI msg<br/>• Inject session_id<br/>• Execute each tool async<br/>• Return ToolMessages"]
        end

        subgraph PostNode["postprocess_node"]
            POST_DESC["• Parse tool results<br/>• Update booking_slots<br/>• Update customer context<br/>• Handle confirmations<br/>• Prepend notifications"]
        end

        subgraph RouterFn["should_continue()"]
            ROUTER_DESC["Routes based on:<br/>has tool_calls? → tools<br/>else → postprocess"]
        end
    end

    PreNode --> AgentNode
    AgentNode --> RouterFn
    RouterFn -->|"tool_calls"| ToolNode
    ToolNode --> AgentNode
    RouterFn -->|"no tools"| PostNode
    PostNode --> END_NODE((END))

    style Graph fill:#1e1b4b,stroke:#6366f1
    style PreNode fill:#312e81,stroke:#8b5cf6
    style AgentNode fill:#1e3a5f,stroke:#3b82f6
    style ToolNode fill:#1e3a3f,stroke:#14b8a6
    style PostNode fill:#3a3a1e,stroke:#eab308
    style RouterFn fill:#3a1e3f,stroke:#d946ef
`

const stateFlowChart = `
flowchart TB
    subgraph State["ConversationState"]
        direction TB

        SESSION[session_id]
        MESSAGES[messages: List]

        subgraph CustomerCtx["Customer Context"]
            CUST_ID[customer_id]
            CUST_NAME[name]
            CUST_PHONE[phone]
            IS_ID[is_identified]
        end

        subgraph BookingCtx["Booking Slots"]
            APPT_TYPE[appointment_type]
            SERVICE[service_type]
            VEHICLE[vehicle_interest]
            DATE[preferred_date]
            TIME[preferred_time]
        end

        subgraph TaskCtx["Background Tasks"]
            PENDING[pending_tasks]
            NOTIF_Q[notifications_queue]
            ESC_PROG[escalation_in_progress]
        end

        CONF[confirmed_appointment]
    end

    subgraph Storage["State Storage"]
        REDIS[(Redis)]
        MEMORY[(In-Memory Fallback)]
    end

    State --> |Persist| REDIS
    REDIS -.-> |Fallback| MEMORY

    style State fill:#1e293b,stroke:#6366f1
    style CustomerCtx fill:#3a1e3f,stroke:#d946ef
    style BookingCtx fill:#1e3a3f,stroke:#14b8a6
    style TaskCtx fill:#3a3a1e,stroke:#eab308
    style Storage fill:#1e3a5f,stroke:#3b82f6
`

export default function AgentFlowDiagram() {
  const mainRef = useRef(null)
  const toolRef = useRef(null)
  const bookingRef = useRef(null)
  const stateRef = useRef(null)
  const graphNodesRef = useRef(null)

  useEffect(() => {
    const renderDiagrams = async () => {
      try {
        if (mainRef.current) {
          const { svg: mainSvg } = await mermaid.render('main-flow', mainFlowChart)
          mainRef.current.innerHTML = mainSvg
        }
        if (toolRef.current) {
          const { svg: toolSvg } = await mermaid.render('tool-flow', toolFlowChart)
          toolRef.current.innerHTML = toolSvg
        }
        if (bookingRef.current) {
          const { svg: bookingSvg } = await mermaid.render('booking-flow', bookingFlowChart)
          bookingRef.current.innerHTML = bookingSvg
        }
        if (stateRef.current) {
          const { svg: stateSvg } = await mermaid.render('state-flow', stateFlowChart)
          stateRef.current.innerHTML = stateSvg
        }
        if (graphNodesRef.current) {
          const { svg: graphNodesSvg } = await mermaid.render('graph-nodes-flow', graphNodesChart)
          graphNodesRef.current.innerHTML = graphNodesSvg
        }
      } catch (error) {
        console.error('Mermaid render error:', error)
      }
    }

    renderDiagrams()
  }, [])

  return (
    <div className="min-h-screen bg-gradient-to-br from-gray-950 via-gray-900 to-gray-950">
      {/* Header */}
      <header className="bg-gray-900/80 backdrop-blur-lg border-b border-gray-800/50 px-6 py-4 sticky top-0 z-40">
        <div className="max-w-7xl mx-auto flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Link
              to="/"
              className="flex items-center gap-2 px-3 py-2 bg-gray-800 hover:bg-gray-700 rounded-lg text-sm transition-colors"
            >
              <ArrowLeft size={16} />
              <span>Back to Dashboard</span>
            </Link>
          </div>
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 bg-gradient-to-br from-purple-500 to-indigo-600 rounded-xl flex items-center justify-center text-xl shadow-lg shadow-purple-500/20">
              <GitBranch size={20} className="text-white" />
            </div>
            <div>
              <h1 className="text-xl font-bold bg-gradient-to-r from-white to-gray-300 bg-clip-text text-transparent">
                Agent Flow Diagram
              </h1>
              <p className="text-sm text-gray-400">System Architecture Visualization</p>
            </div>
          </div>
          <div></div>
        </div>
      </header>

      {/* Main Content */}
      <main className="max-w-7xl mx-auto p-6 space-y-8">

        {/* Main Architecture */}
        <section className="bg-gray-900/50 backdrop-blur border border-gray-800/50 rounded-2xl overflow-hidden">
          <div className="px-6 py-4 bg-gradient-to-r from-indigo-900/30 to-purple-900/30 border-b border-gray-700/50">
            <h2 className="text-lg font-semibold text-white">System Architecture</h2>
            <p className="text-sm text-gray-400 mt-1">Twilio voice pipeline, backend, and LangGraph workflow</p>
          </div>
          <div className="p-6 overflow-x-auto">
            <div ref={mainRef} className="flex justify-center min-w-[800px]" />
          </div>
        </section>

        {/* Graph Nodes Detail - Full Width */}
        <section className="bg-gray-900/50 backdrop-blur border border-gray-800/50 rounded-2xl overflow-hidden">
          <div className="px-6 py-4 bg-gradient-to-r from-violet-900/30 to-fuchsia-900/30 border-b border-gray-700/50">
            <h2 className="text-lg font-semibold text-white">LangGraph Nodes Detail</h2>
            <p className="text-sm text-gray-400 mt-1">What each node in the graph does (graph.py)</p>
          </div>
          <div className="p-6 overflow-x-auto">
            <div ref={graphNodesRef} className="flex justify-center min-w-[900px]" />
          </div>
        </section>

        {/* Two column layout */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">

          {/* Available Tools */}
          <section className="bg-gray-900/50 backdrop-blur border border-gray-800/50 rounded-2xl overflow-hidden">
            <div className="px-6 py-4 bg-gradient-to-r from-teal-900/30 to-cyan-900/30 border-b border-gray-700/50">
              <h2 className="text-lg font-semibold text-white">Available Tools</h2>
              <p className="text-sm text-gray-400 mt-1">All 15 tools the agent can use</p>
            </div>
            <div className="p-6 overflow-x-auto">
              <div ref={toolRef} className="flex justify-center" />
            </div>
          </section>

          {/* State Structure */}
          <section className="bg-gray-900/50 backdrop-blur border border-gray-800/50 rounded-2xl overflow-hidden">
            <div className="px-6 py-4 bg-gradient-to-r from-yellow-900/30 to-orange-900/30 border-b border-gray-700/50">
              <h2 className="text-lg font-semibold text-white">Conversation State</h2>
              <p className="text-sm text-gray-400 mt-1">State structure and persistence</p>
            </div>
            <div className="p-6 overflow-x-auto">
              <div ref={stateRef} className="flex justify-center" />
            </div>
          </section>
        </div>

        {/* Booking Flow */}
        <section className="bg-gray-900/50 backdrop-blur border border-gray-800/50 rounded-2xl overflow-hidden">
          <div className="px-6 py-4 bg-gradient-to-r from-green-900/30 to-emerald-900/30 border-b border-gray-700/50">
            <h2 className="text-lg font-semibold text-white">Booking Flow</h2>
            <p className="text-sm text-gray-400 mt-1">Step-by-step booking process with tool calls</p>
          </div>
          <div className="p-6 overflow-x-auto">
            <div ref={bookingRef} className="flex justify-center min-w-[600px]" />
          </div>
        </section>

        {/* Legend */}
        <section className="bg-gray-900/50 backdrop-blur border border-gray-800/50 rounded-2xl p-6">
          <h2 className="text-lg font-semibold text-white mb-4">Key Components</h2>
          <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
            <div className="flex items-center gap-3">
              <div className="w-4 h-4 rounded bg-indigo-500"></div>
              <span className="text-sm text-gray-300">LangGraph Workflow</span>
            </div>
            <div className="flex items-center gap-3">
              <div className="w-4 h-4 rounded bg-violet-500"></div>
              <span className="text-sm text-gray-300">Graph Nodes</span>
            </div>
            <div className="flex items-center gap-3">
              <div className="w-4 h-4 rounded bg-teal-500"></div>
              <span className="text-sm text-gray-300">Agent Tools</span>
            </div>
            <div className="flex items-center gap-3">
              <div className="w-4 h-4 rounded bg-blue-500"></div>
              <span className="text-sm text-gray-300">Twilio Voice</span>
            </div>
            <div className="flex items-center gap-3">
              <div className="w-4 h-4 rounded bg-yellow-500"></div>
              <span className="text-sm text-gray-300">State Management</span>
            </div>
          </div>

          {/* Node Function Summary */}
          <div className="mt-6 pt-6 border-t border-gray-700/50">
            <h3 className="text-md font-semibold text-white mb-3">Graph Node Functions</h3>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 text-sm">
              <div className="bg-violet-900/20 border border-violet-700/30 rounded-lg p-3">
                <div className="font-medium text-violet-300 mb-1">preprocess_node</div>
                <div className="text-gray-400 text-xs">Processes notifications from background tasks (escalation results)</div>
              </div>
              <div className="bg-blue-900/20 border border-blue-700/30 rounded-lg p-3">
                <div className="font-medium text-blue-300 mb-1">agent_node</div>
                <div className="text-gray-400 text-xs">Invokes LLM with tools bound - all decision making happens here</div>
              </div>
              <div className="bg-teal-900/20 border border-teal-700/30 rounded-lg p-3">
                <div className="font-medium text-teal-300 mb-1">tool_node</div>
                <div className="text-gray-400 text-xs">Executes tool calls and returns results back to agent</div>
              </div>
              <div className="bg-yellow-900/20 border border-yellow-700/30 rounded-lg p-3">
                <div className="font-medium text-yellow-300 mb-1">postprocess_node</div>
                <div className="text-gray-400 text-xs">Parses tool results, updates state, handles confirmations</div>
              </div>
            </div>
          </div>
        </section>

      </main>
    </div>
  )
}
