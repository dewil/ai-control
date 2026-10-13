package ru.dewil.aicontrol.policy
import org.junit.Assert.assertEquals
import org.junit.Test
/** INV-WATT-09: only exact upload subresource PUT, never broad navigation. */
class OriginPolicyUploadBlindTest {
 private val origin="https://llm-web.dewil.ru:18443"
 private val route="/api/session-attachment-chunk"
 private val query="?attachment_id=00000000-0000-4000-8000-000000000001&index=0"
 private fun decision(url:String, main:Boolean=false, redirect:Boolean=false, method:String="PUT")=OriginPolicy.classify(url,main,false,method,redirect)
 @Test fun INV_WATT_09_exactPanelChunkPutSubresourceIsAllowed() {
  assertEquals(NavigationDecision.ALLOW_PANEL,decision(origin+route+query))
  assertEquals(NavigationDecision.ALLOW_PANEL,decision(origin+route))
  // Authenticated HTTP route owns UUID/index validation.
  assertEquals(NavigationDecision.ALLOW_PANEL,decision(origin+route+"?attachment_id=bad&index=-1"))
 }
 @Test fun INV_WATT_09_mainFrameRedirectFragmentRemainBlocked() {
  assertEquals(NavigationDecision.BLOCK,decision(origin+route+query,main=true))
  assertEquals(NavigationDecision.BLOCK,decision(origin+route+query,redirect=true))
  assertEquals(NavigationDecision.BLOCK,decision(origin+route+query+"#fragment"))
 }
 @Test fun INV_WATT_09_foreignOtherPathsAndOtherMethodsRemainBlocked() {
  listOf("/","/api/session-send","/api/session-attachment-begin","/api/session-attachment-chunk/","/api/session-attachment-chunk/extra","/download/android/").forEach {assertEquals(it,NavigationDecision.BLOCK,decision(origin+it+query))}
  listOf("https://foreign.invalid:18443","https://llm-web.dewil.ru","http://llm-web.dewil.ru:18443","https://llm-web.dewil.ru.evil.invalid:18443","https://user@llm-web.dewil.ru:18443").forEach {assertEquals(it,NavigationDecision.BLOCK,decision(it+route+query))}
  listOf("put","PATCH","DELETE","OPTIONS").forEach {assertEquals(it,NavigationDecision.BLOCK,decision(origin+route+query,method=it))}
 }
}
