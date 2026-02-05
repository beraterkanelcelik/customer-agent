import React, { useEffect, useRef } from 'react'
import { Link } from 'react-router-dom'
import { ArrowLeft, GitBranch } from 'lucide-react'
import mermaid from 'mermaid'

// Initialize mermaid with soft light theme
mermaid.initialize({
  startOnLoad: false,
  theme: 'base',
  themeVariables: {
    primaryColor: '#d4f1f4',
    primaryTextColor: '#1a3a47',
    primaryBorderColor: '#22a1b3',
    lineColor: '#7a9aaa',
    secondaryColor: '#e8f2f8',
    tertiaryColor: '#f0fafb',
    background: '#fafcfd',
    mainBkg: '#ffffff',
    nodeBorder: '#22a1b3',
    clusterBkg: '#f5f9fc',
    clusterBorder: '#c5d9e4',
    titleColor: '#1a3a47',
    edgeLabelBackground: '#ffffff',
    textColor: '#1a3a47',
    nodeTextColor: '#1a3a47'
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

    style Twilio fill:#e8f2f8,stroke:#4193c0
    style Backend fill:#f0fafb,stroke:#22a1b3
    style LangGraph fill:#f5f0ff,stroke:#8b5cf6
    style Capabilities fill:#f0fdf6,stroke:#22c563
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

    style FAQ_Tools fill:#e8f2f8,stroke:#4193c0
    style Booking_Tools fill:#f0fdf6,stroke:#22c563
    style Customer_Tools fill:#fdf4ff,stroke:#d946ef
    style Slot_Tools fill:#fefce8,stroke:#eab308
    style Call_Tools fill:#fef2f2,stroke:#ef4444
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

    style START fill:#d4f1f4,stroke:#22a1b3
    style SUCCESS fill:#dcfce9,stroke:#22c563
    style CREATE fill:#fae8ff,stroke:#d946ef
    style BOOK fill:#ccfbf1,stroke:#14b8a6
    style CHECK fill:#fef9c3,stroke:#eab308
    style LIST fill:#dbeafe,stroke:#3b82f6
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

    style Graph fill:#f5f0ff,stroke:#8b5cf6
    style PreNode fill:#ede9fe,stroke:#8b5cf6
    style AgentNode fill:#e8f2f8,stroke:#4193c0
    style ToolNode fill:#f0fdf6,stroke:#22c563
    style PostNode fill:#fefce8,stroke:#eab308
    style RouterFn fill:#fdf4ff,stroke:#d946ef
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

    style State fill:#f0fafb,stroke:#22a1b3
    style CustomerCtx fill:#fdf4ff,stroke:#d946ef
    style BookingCtx fill:#f0fdf6,stroke:#22c563
    style TaskCtx fill:#fefce8,stroke:#eab308
    style Storage fill:#e8f2f8,stroke:#4193c0
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
    <div className="min-h-screen relative">
      {/* Header */}
      <header className="glass-card-solid sticky top-0 z-40 border-b border-surface-300/50">
        <div className="max-w-7xl mx-auto px-6 py-4">
          <div className="flex items-center justify-between">
            <Link
              to="/"
              className="flex items-center gap-2 px-4 py-2.5 bg-white/60 hover:bg-white border border-surface-300 hover:border-accent-300 rounded-xl text-sm text-slate-600 hover:text-accent-600 transition-all duration-200 shadow-sm hover:shadow"
            >
              <ArrowLeft size={16} />
              <span className="font-medium">Back to Dashboard</span>
            </Link>

            <div className="flex items-center gap-4 animate-fade-in">
              <div className="w-12 h-12 bg-gradient-to-br from-accent-400 to-soft-500 rounded-2xl flex items-center justify-center shadow-soft">
                <GitBranch size={22} className="text-white" />
              </div>
              <div>
                <h1 className="text-xl font-bold text-slate-800 font-display">
                  Agent Flow Diagram
                </h1>
                <p className="text-sm text-slate-500">System Architecture Visualization</p>
              </div>
            </div>

            <div className="w-[140px]"></div>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="max-w-7xl mx-auto p-6 space-y-8 relative z-10">

        {/* Main Architecture */}
        <section className="glass-card rounded-3xl overflow-hidden shadow-glass-lg animate-fade-in-up" style={{ animationDelay: '0.1s' }}>
          <div className="px-6 py-5 bg-gradient-to-r from-soft-50 to-accent-50 border-b border-surface-200/50">
            <h2 className="text-lg font-semibold text-slate-800">System Architecture</h2>
            <p className="text-sm text-slate-500 mt-1">Twilio voice pipeline, backend, and LangGraph workflow</p>
          </div>
          <div className="p-6 overflow-x-auto bg-white/40">
            <div ref={mainRef} className="flex justify-center min-w-[800px]" />
          </div>
        </section>

        {/* Graph Nodes Detail - Full Width */}
        <section className="glass-card rounded-3xl overflow-hidden shadow-glass-lg animate-fade-in-up" style={{ animationDelay: '0.2s' }}>
          <div className="px-6 py-5 bg-gradient-to-r from-violet-50 to-purple-50 border-b border-surface-200/50">
            <h2 className="text-lg font-semibold text-slate-800">LangGraph Nodes Detail</h2>
            <p className="text-sm text-slate-500 mt-1">What each node in the graph does (graph.py)</p>
          </div>
          <div className="p-6 overflow-x-auto bg-white/40">
            <div ref={graphNodesRef} className="flex justify-center min-w-[900px]" />
          </div>
        </section>

        {/* Two column layout */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">

          {/* Available Tools */}
          <section className="glass-card rounded-3xl overflow-hidden shadow-glass-lg animate-fade-in-up" style={{ animationDelay: '0.3s' }}>
            <div className="px-6 py-5 bg-gradient-to-r from-accent-50 to-success-50 border-b border-surface-200/50">
              <h2 className="text-lg font-semibold text-slate-800">Available Tools</h2>
              <p className="text-sm text-slate-500 mt-1">All 15 tools the agent can use</p>
            </div>
            <div className="p-6 overflow-x-auto bg-white/40">
              <div ref={toolRef} className="flex justify-center" />
            </div>
          </section>

          {/* State Structure */}
          <section className="glass-card rounded-3xl overflow-hidden shadow-glass-lg animate-fade-in-up" style={{ animationDelay: '0.4s' }}>
            <div className="px-6 py-5 bg-gradient-to-r from-warning-50 to-yellow-50 border-b border-surface-200/50">
              <h2 className="text-lg font-semibold text-slate-800">Conversation State</h2>
              <p className="text-sm text-slate-500 mt-1">State structure and persistence</p>
            </div>
            <div className="p-6 overflow-x-auto bg-white/40">
              <div ref={stateRef} className="flex justify-center" />
            </div>
          </section>
        </div>

        {/* Booking Flow */}
        <section className="glass-card rounded-3xl overflow-hidden shadow-glass-lg animate-fade-in-up" style={{ animationDelay: '0.5s' }}>
          <div className="px-6 py-5 bg-gradient-to-r from-success-50 to-emerald-50 border-b border-surface-200/50">
            <h2 className="text-lg font-semibold text-slate-800">Booking Flow</h2>
            <p className="text-sm text-slate-500 mt-1">Step-by-step booking process with tool calls</p>
          </div>
          <div className="p-6 overflow-x-auto bg-white/40">
            <div ref={bookingRef} className="flex justify-center min-w-[600px]" />
          </div>
        </section>

        {/* Legend */}
        <section className="glass-card rounded-3xl p-6 shadow-glass-lg animate-fade-in-up" style={{ animationDelay: '0.6s' }}>
          <h2 className="text-lg font-semibold text-slate-800 mb-5">Key Components</h2>
          <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
            <div className="flex items-center gap-3 p-3 bg-white/60 rounded-xl border border-surface-200">
              <div className="w-4 h-4 rounded-lg bg-gradient-to-br from-accent-400 to-accent-500"></div>
              <span className="text-sm text-slate-600 font-medium">LangGraph Workflow</span>
            </div>
            <div className="flex items-center gap-3 p-3 bg-white/60 rounded-xl border border-surface-200">
              <div className="w-4 h-4 rounded-lg bg-gradient-to-br from-violet-400 to-violet-500"></div>
              <span className="text-sm text-slate-600 font-medium">Graph Nodes</span>
            </div>
            <div className="flex items-center gap-3 p-3 bg-white/60 rounded-xl border border-surface-200">
              <div className="w-4 h-4 rounded-lg bg-gradient-to-br from-success-400 to-success-500"></div>
              <span className="text-sm text-slate-600 font-medium">Agent Tools</span>
            </div>
            <div className="flex items-center gap-3 p-3 bg-white/60 rounded-xl border border-surface-200">
              <div className="w-4 h-4 rounded-lg bg-gradient-to-br from-soft-400 to-soft-500"></div>
              <span className="text-sm text-slate-600 font-medium">Twilio Voice</span>
            </div>
            <div className="flex items-center gap-3 p-3 bg-white/60 rounded-xl border border-surface-200">
              <div className="w-4 h-4 rounded-lg bg-gradient-to-br from-warning-400 to-warning-500"></div>
              <span className="text-sm text-slate-600 font-medium">State Management</span>
            </div>
          </div>

          {/* Node Function Summary */}
          <div className="mt-6 pt-6 border-t border-surface-200">
            <h3 className="text-md font-semibold text-slate-800 mb-4">Graph Node Functions</h3>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 text-sm">
              <div className="bg-violet-50/80 border border-violet-200 rounded-2xl p-4 transition-all duration-200 hover:shadow-soft">
                <div className="font-semibold text-violet-700 mb-2">preprocess_node</div>
                <div className="text-slate-500 text-xs leading-relaxed">Processes notifications from background tasks (escalation results)</div>
              </div>
              <div className="bg-soft-50/80 border border-soft-200 rounded-2xl p-4 transition-all duration-200 hover:shadow-soft">
                <div className="font-semibold text-soft-700 mb-2">agent_node</div>
                <div className="text-slate-500 text-xs leading-relaxed">Invokes LLM with tools bound - all decision making happens here</div>
              </div>
              <div className="bg-success-50/80 border border-success-200 rounded-2xl p-4 transition-all duration-200 hover:shadow-soft">
                <div className="font-semibold text-success-700 mb-2">tool_node</div>
                <div className="text-slate-500 text-xs leading-relaxed">Executes tool calls and returns results back to agent</div>
              </div>
              <div className="bg-warning-50/80 border border-warning-200 rounded-2xl p-4 transition-all duration-200 hover:shadow-soft">
                <div className="font-semibold text-warning-700 mb-2">postprocess_node</div>
                <div className="text-slate-500 text-xs leading-relaxed">Parses tool results, updates state, handles confirmations</div>
              </div>
            </div>
          </div>
        </section>

      </main>
    </div>
  )
}
