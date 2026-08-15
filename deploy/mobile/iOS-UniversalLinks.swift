// iOS Universal Links handler — Patient app (Bundle: com.mediik.patient)
//
// Setup steps:
// 1. Xcode → Project → Signing & Capabilities → + Capability → Associated Domains
// 2. Add: applinks:app.mediik.uz
// 3. Production build kerak — Universal Links debug build'da ko'pincha ishlamaydi
// 4. AASA fayl https://app.mediik.uz/.well-known/apple-app-site-association
//    da host qilingan va validator (https://branch.io/resources/aasa-validator/)
//    "valid" deb tasdiqlagan bo'lishi kerak.

import SwiftUI
import UIKit

// MARK: - SwiftUI App-level handler

@main
struct MediikPatientApp: App {
    @StateObject private var deepLinkRouter = DeepLinkRouter()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(deepLinkRouter)
                .onContinueUserActivity(NSUserActivityTypeBrowsingWeb) { activity in
                    guard let url = activity.webpageURL else { return }
                    deepLinkRouter.handle(url: url)
                }
        }
    }
}

// MARK: - Router

final class DeepLinkRouter: ObservableObject {
    @Published var pendingDestination: Destination?

    enum Destination: Equatable {
        case paymentResult(paymentId: Int, status: PaymentStatus)
        case paymentCancelled(paymentId: Int)
        case appointment(id: Int)
        case dietConversation(id: Int)
        case chatRoom(id: Int)
        case referral(code: String)
    }

    enum PaymentStatus: String {
        case success
        case fail
    }

    func handle(url: URL) {
        // URL: https://app.mediik.uz/payment/return?payment_id=42&status=success
        guard let components = URLComponents(url: url, resolvingAgainstBaseURL: false),
              components.host == "app.mediik.uz" else {
            return
        }

        let path = components.path
        let query = Dictionary(uniqueKeysWithValues:
            (components.queryItems ?? []).compactMap { item -> (String, String)? in
                guard let value = item.value else { return nil }
                return (item.name, value)
            }
        )

        switch path {
        case "/payment/return":
            guard let id = Int(query["payment_id"] ?? ""),
                  let status = PaymentStatus(rawValue: query["status"] ?? "") else { return }
            pendingDestination = .paymentResult(paymentId: id, status: status)

        case "/payment/cancel":
            guard let id = Int(query["payment_id"] ?? "") else { return }
            pendingDestination = .paymentCancelled(paymentId: id)

        case let p where p.hasPrefix("/appointment/"):
            let id = Int(p.dropFirst("/appointment/".count)) ?? 0
            if id > 0 { pendingDestination = .appointment(id: id) }

        case let p where p.hasPrefix("/diet/conversation/"):
            let id = Int(p.dropFirst("/diet/conversation/".count)) ?? 0
            if id > 0 { pendingDestination = .dietConversation(id: id) }

        case let p where p.hasPrefix("/chat/"):
            let id = Int(p.dropFirst("/chat/".count)) ?? 0
            if id > 0 { pendingDestination = .chatRoom(id: id) }

        case let p where p.hasPrefix("/ref/"):
            let code = String(p.dropFirst("/ref/".count))
            if !code.isEmpty { pendingDestination = .referral(code: code) }

        default:
            break
        }
    }
}

// MARK: - Usage in views

struct ContentView: View {
    @EnvironmentObject var router: DeepLinkRouter

    var body: some View {
        NavigationStack {
            // ... your main UI
            Text("Mediik Patient")
        }
        .onChange(of: router.pendingDestination) { destination in
            guard let destination = destination else { return }
            // Navigate based on destination
            switch destination {
            case .paymentResult(let id, let status):
                // Navigate to payment result screen
                print("Payment \(id) → \(status.rawValue)")
            case .appointment(let id):
                print("Open appointment \(id)")
            // ... handle others
            default:
                break
            }
            router.pendingDestination = nil  // Clear after handling
        }
    }
}
