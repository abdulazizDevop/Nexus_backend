// Android App Links handler — Patient app
//
// Setup steps:
// 1. AndroidManifest.xml — intent-filter qo'shing (pastda)
// 2. assetlinks.json https://app.mediik.uz/.well-known/assetlinks.json da host qilinsin
// 3. Production keystore SHA-256 fingerprint to'g'ri ekanini tasdiqlash:
//    https://digitalassetlinks.googleapis.com/v1/statements:list?source.web.site=https://app.mediik.uz&relation=delegate_permission/common.handle_all_urls
// 4. App o'rnatilgandan keyin Android avtomatik AASA tekshirib link'ni app'ga
//    yo'naltiradi (autoVerify="true" tufayli).

/* ============================================================
 * AndroidManifest.xml
 * ============================================================
 *
 * <manifest ...>
 *   <application ...>
 *     <activity
 *         android:name=".MainActivity"
 *         android:exported="true"
 *         android:launchMode="singleTask">
 *
 *       <!-- Default launcher -->
 *       <intent-filter>
 *         <action android:name="android.intent.action.MAIN" />
 *         <category android:name="android.intent.category.LAUNCHER" />
 *       </intent-filter>
 *
 *       <!-- App Links — autoVerify=true majburiy -->
 *       <intent-filter android:autoVerify="true">
 *         <action android:name="android.intent.action.VIEW" />
 *         <category android:name="android.intent.category.DEFAULT" />
 *         <category android:name="android.intent.category.BROWSABLE" />
 *         <data android:scheme="https"
 *               android:host="app.mediik.uz" />
 *       </intent-filter>
 *
 *     </activity>
 *   </application>
 * </manifest>
 */

package com.mediik.patient

import android.content.Intent
import android.net.Uri
import android.os.Bundle
import androidx.activity.ComponentActivity

class MainActivity : ComponentActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // Cold start — app yopiq edi va deep-link orqali ochildi
        handleDeepLink(intent)
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        // Hot start — app allaqachon ochiq edi
        handleDeepLink(intent)
    }

    private fun handleDeepLink(intent: Intent) {
        val data: Uri = intent.data ?: return
        if (data.host != "app.mediik.uz") return

        when {
            data.path == "/payment/return" -> {
                val paymentId = data.getQueryParameter("payment_id")?.toIntOrNull() ?: return
                val status = data.getQueryParameter("status") ?: "unknown"
                navigateToPaymentResult(paymentId, status)
            }

            data.path == "/payment/cancel" -> {
                val paymentId = data.getQueryParameter("payment_id")?.toIntOrNull() ?: return
                navigateToPaymentCancelled(paymentId)
            }

            data.path?.startsWith("/appointment/") == true -> {
                val id = data.path?.removePrefix("/appointment/")?.toIntOrNull() ?: return
                navigateToAppointment(id)
            }

            data.path?.startsWith("/diet/conversation/") == true -> {
                val id = data.path?.removePrefix("/diet/conversation/")?.toIntOrNull() ?: return
                navigateToDietConversation(id)
            }

            data.path?.startsWith("/chat/") == true -> {
                val id = data.path?.removePrefix("/chat/")?.toIntOrNull() ?: return
                navigateToChat(id)
            }

            data.path?.startsWith("/ref/") == true -> {
                val code = data.path?.removePrefix("/ref/") ?: return
                if (code.isNotEmpty()) navigateToReferral(code)
            }
        }
    }

    private fun navigateToPaymentResult(paymentId: Int, status: String) {
        // TODO: navigate to payment result screen
        // Misol: Compose Navigation
        // navController.navigate("payment/result/$paymentId?status=$status")
    }

    private fun navigateToPaymentCancelled(paymentId: Int) { /* ... */ }
    private fun navigateToAppointment(id: Int) { /* ... */ }
    private fun navigateToDietConversation(id: Int) { /* ... */ }
    private fun navigateToChat(id: Int) { /* ... */ }
    private fun navigateToReferral(code: String) { /* ... */ }
}
